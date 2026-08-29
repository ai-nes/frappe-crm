import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from crm.fcrm.doctype.crm_student.enrollment_transition import (
	record_transition,
	set_enrollment_status,
)
from crm.fcrm.lifecycle import enforce_lifecycle_change_policy, get_lifecycle_stage
from crm.fcrm.permissions import derive_owner_fields, derive_unassigned_owning_team
from crm.fcrm.utils.geo_resolver import (
	resolve_high_school_strict,
	resolve_province,
	resolve_ward,
)


class CRMStudent(Document):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# Frappe's _validate_links() runs before before_insert/before_save/validate
		# and throws its own generic error for any Link field holding free-text
		# input (e.g. high_school/province/ward from a Data Import row), before our
		# resolvers ever get a chance to run. We disable it here and re-run it
		# ourselves at the end of validate(), once geo fields are resolved.
		self.flags.ignore_links = True

	def before_insert(self):
		if not getattr(frappe.flags, "student_intake_service", False):
			frappe.throw(
				_("New CRM Students must be created through the Student intake command."),
				title=_("Student intake required"),
			)
		self._set_defaults()
		self._normalize_phone_fields()
		self._resolve_geo()

	def before_save(self):
		before = self.get_doc_before_save()
		if before and not getattr(frappe.flags, "student_lifecycle_service", False):
			lifecycle_fields = ("enrollment_status", "lifecycle_stage")
			if any(before.get(field) != self.get(field) for field in lifecycle_fields):
				frappe.throw(
					_("Student lifecycle changes must use the lifecycle transition command."),
					frappe.PermissionError,
					title=_("Lifecycle command required"),
				)
		if before and not getattr(frappe.flags, "student_ownership_service", False):
			ownership_fields = ("assigned_to", "owner_staff", "owning_team", "owning_pool")
			if any(before.get(field) != self.get(field) for field in ownership_fields):
				frappe.throw(
					_("Student ownership changes must use the ownership command."),
					title=_("Ownership command required"),
				)
		self._normalize_phone_fields()
		self._resolve_geo()
		if self.cohort_end_year:
			self.cohort_start_year = int(self.cohort_end_year) - 3

	def validate(self):
		self._validate_phone_format()
		self._resolve_geo()
		self._validate_high_school_format()
		if getattr(frappe.flags, "student_intake_service", False) or getattr(frappe.flags, "student_ownership_service", False) or not self.get_doc_before_save():
			self._derive_owner_fields()
		self._derive_lifecycle_stage()
		if getattr(frappe.flags, "student_ownership_service", False):
			self._log_assignment_change()
		self.flags.ignore_links = False
		self._validate_links()

	def _derive_owner_fields(self):
		if self.assigned_to:
			self.owner_staff, self.owning_team = derive_owner_fields(self.assigned_to)
			return
		self.owner_staff = None
		if not self.owning_team:
			self.owning_team = derive_unassigned_owning_team(frappe.session.user)

	def _derive_lifecycle_stage(self):
		before = self.get_doc_before_save()
		before_enrollment_status = before.enrollment_status if before else None
		self.lifecycle_stage = get_lifecycle_stage(self.enrollment_status)
		enforce_lifecycle_change_policy(self, before_enrollment_status)

	def _log_assignment_change(self):
		before = self.get_doc_before_save()
		before_assigned_to = before.assigned_to if before else None
		if before_assigned_to == self.assigned_to:
			return
		self.append(
			"assignment_log",
			{
				"from_staff": before_assigned_to,
				"to_staff": self.assigned_to,
				"changed_by": frappe.session.user,
				"changed_at": now_datetime(),
				"auto_routed": 0,
				"reason": self.status_change_reason,
			},
		)

	def _validate_high_school_format(self):
		if not self.high_school:
			return
		self.high_school = resolve_high_school_strict(self.high_school, self.province)

	def _validate_phone_format(self):
		if not self.phone:
			return
		phone = self.phone.strip()
		if phone.startswith("+84"):
			phone = "0" + phone[3:]
		self.phone = phone
		if not re.fullmatch(r"0\d{9}", phone):
			frappe.throw(
				f"Số điện thoại <b>{phone}</b> không hợp lệ. Số điện thoại phải gồm đúng 10 số.",
				title="Số điện thoại không hợp lệ",
			)

	def on_update(self):
		self._log_enrollment_transition()
		before = self.get_doc_before_save()
		from crm.services.student_context import bump_student_context_revision, material_student_changed

		if material_student_changed(self, before):
			bump_student_context_revision(self.name, "student_material_change")
		from crm.services.score_revision import bump_score_input_revision, student_score_input_changed

		if student_score_input_changed(self, before):
			bump_score_input_revision(self.name, "student_field_scoring_change")

	def _log_enrollment_transition(self):
		# Fires on both insert and update (Frappe calls on_update after
		# db_insert too) — the single hook-side entry point into
		# record_transition(). Does NOT catch the db_set/db.set_value
		# bypass paths (convert-to-contact, Contact-side edit) — those
		# call set_enrollment_status() directly instead, since db_set
		# skips this hook entirely.
		before = self.get_doc_before_save()
		if before is None:
			# New student — get_doc_before_save() is only populated on the
			# update path (load_doc_before_save runs before db_update, not
			# before db_insert). Record the initial status so it isn't
			# invisible in the log.
			record_transition(self.name, None, self.enrollment_status, source="student_insert")
			return

		old_status = before.get("enrollment_status")
		if old_status != self.enrollment_status:
			record_transition(self.name, old_status, self.enrollment_status, source="student_save")

	def _set_defaults(self):
		if not self.admission_year:
			current_year = str(frappe.utils.now_datetime().year)
			if frappe.db.exists("CRM Admission Year", current_year):
				self.admission_year = current_year
		if not self.branch:
			default_branch = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
			if default_branch:
				self.branch = default_branch

	def _resolve_geo(self):
		# high_school is intentionally NOT resolved here — _validate_high_school_format()
		# is the single source of truth for it (resolve_high_school_strict), called right
		# after this in validate(). Resolving it twice would be wasted work whose result
		# gets discarded.
		if self.province:
			self.province = resolve_province(self.province)
		if self.ward:
			self.ward = resolve_ward(self.ward, self.province)

	def _normalize_phone_fields(self):
		if isinstance(self.phone, str):
			self.phone = self.phone.strip()
		if isinstance(self.email, str):
			self.email = self.email.strip().lower()
		if isinstance(self.id_number, str):
			self.id_number = self.id_number.strip()

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Student Name",
				"type": "Data",
				"key": "student_name",
				"width": "16rem",
			},
			{
				"label": "Phone",
				"type": "Data",
				"key": "phone",
				"width": "10rem",
			},
			{
				"label": "Email",
				"type": "Data",
				"key": "email",
				"width": "14rem",
			},
			{
				"label": "Enrollment Status",
				"type": "Link",
				"key": "enrollment_status",
				"options": "CRM Term",
				"width": "12rem",
			},
			{
				"label": "Assigned To",
				"type": "Link",
				"key": "assigned_to",
				"options": "CRM Staff",
				"width": "12rem",
			},
			{
				"label": "Source",
				"type": "Link",
				"key": "source",
				"options": "CRM Lead Source",
				"width": "10rem",
			},
			{
				"label": "Last Modified",
				"type": "Datetime",
				"key": "modified",
				"width": "8rem",
			},
		]
		rows = [
			"name",
			"student_name",
			"phone",
			"email",
			"enrollment_status",
			"assigned_to",
			"source",
			"modified",
		]
		return {"columns": columns, "rows": rows}


@frappe.whitelist()
def convert_to_contact(
	student_name,
	expected_lifecycle_revision=None,
	idempotency_key=None,
	correlation_id=None,
):
	"""Retained route for old clients; it cannot bypass the conversion command."""
	if expected_lifecycle_revision in (None, "") or not str(idempotency_key or "").strip():
		frappe.throw(
			_("CONVERSION_ENDPOINT_RETIRED: use crm.api.student_conversion.convert_student."),
			frappe.ValidationError,
		)
	from crm.fcrm.student_conversion import convert_student

	return convert_student(
		student=student_name,
		expected_lifecycle_revision=expected_lifecycle_revision,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
	)


@frappe.whitelist()
def create_from_contact(contact):
	# Contact is post-conversion identity data. Creating an admissions Student
	# from it bypasses identity/cycle resolution, review, pool selection, and
	# command receipts; the canonical intake service is the only allowed writer.
	frappe.throw(_("Creating a Student from Contact is retired; use the Student intake command."), frappe.PermissionError)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as _scoped

	return _scoped("CRM Student", user=user)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	from crm.fcrm.permissions import has_permission as _scoped

	return _scoped(doc, user=user, permission_type=permission_type, ptype=ptype)
