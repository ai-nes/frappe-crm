import re

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from crm.api.routing import route_new_lead
from crm.fcrm.lifecycle import enforce_lifecycle_change_policy, get_lifecycle_stage
from crm.fcrm.permissions import derive_owner_fields, derive_unassigned_owning_team
from crm.fcrm.utils.geo_resolver import resolve_high_school_strict, resolve_province

# CRM Enrollment Status values that constitute the "application/enrollment" milestone
# at which a CRM Student record should be created for a Contact — locked business
# rule, see plans/260822-admissions-crm-alignment/phase-02-fix-contact-student-lifecycle-bug.md.
MILESTONE_ENROLLMENT_STATUSES = {"Đã xác nhận", "Đã nhập học"}


class CRMContact(Document):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# See CRMStudent.__init__ — Frappe's _validate_links() runs before
		# before_insert/before_save/validate and breaks free-text Link field
		# resolution (high_school/province). Disabled here, re-run at the end
		# of validate() once those fields are resolved.
		self.flags.ignore_links = True

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Full Name",
				"type": "Data",
				"key": "full_name",
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
				"options": "CRM Enrollment Status",
				"width": "10rem",
			},
			{
				"label": "Assigned To",
				"type": "Link",
				"key": "assigned_to",
				"options": "CRM Staff",
				"width": "12rem",
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
			"full_name",
			"phone",
			"email",
			"enrollment_status",
			"assigned_to",
			"modified",
		]
		return {"columns": columns, "rows": rows}

	@staticmethod
	def default_kanban_settings():
		return {
			"title_field": "full_name",
			"kanban_fields": '["name", "full_name", "phone", "email", "enrollment_status", "assigned_to"]',
		}

	def before_insert(self):
		self._set_defaults()
		self._normalize_shared_fields()
		self._sync_fields_from_student_if_blank()
		self._resolve_geo()
		route_new_lead(self)

	def _set_defaults(self):
		if not self.admission_year:
			current_year = str(frappe.utils.now_datetime().year)
			if frappe.db.exists("CRM Admission Year", current_year):
				self.admission_year = current_year
		if not self.branch:
			default_branch = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
			if default_branch:
				self.branch = default_branch

	def before_save(self):
		self._normalize_shared_fields()
		self._sync_fields_from_student_if_blank()
		self._resolve_geo()

	def on_update(self):
		self._create_student_at_milestone()

	def validate(self):
		self._normalize_shared_fields()
		self._validate_phone_format()
		self._resolve_geo()
		self._validate_high_school_format()
		self._validate_unique_phone()
		self._validate_unique_email()
		self._derive_owner_fields()
		self._derive_lifecycle_stage()
		self._log_assignment_change()
		self._track_sla_start()
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
				"auto_routed": 1 if self.flags.auto_routed else 0,
				"reason": self.status_change_reason,
			},
		)

	def _track_sla_start(self):
		if self.assigned_to and not self.sla_started_at:
			self.sla_started_at = now_datetime()

	def _resolve_geo(self):
		# high_school is intentionally NOT resolved here — _validate_high_school_format()
		# is the single source of truth for it (resolve_high_school_strict), called right
		# after this in validate(). Resolving it twice would be wasted work whose result
		# gets discarded.
		if self.province:
			self.province = resolve_province(self.province)

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

	def _validate_unique_phone(self):
		if not self.phone:
			return
		existing = frappe.db.get_value(
			"CRM Contact",
			{"phone": self.phone, "name": ("!=", self.name or "")},
			["name", "full_name"],
			as_dict=True,
		)
		if existing:
			frappe.throw(
				f"Số điện thoại <b>{self.phone}</b> đã tồn tại trong liên hệ "
				f'<a href="/crm/contacts/{existing.name}">{existing.full_name}</a>',
				title="Số điện thoại trùng",
			)
		existing_student = frappe.db.get_value(
			"CRM Student",
			{"phone": self.phone, "name": ("!=", self.student or "")},
			["name", "student_name"],
			as_dict=True,
		)
		if existing_student:
			frappe.throw(
				f"Số điện thoại <b>{self.phone}</b> đã tồn tại ở học sinh "
				f'<a href="/crm/crm-students/{existing_student.name}">{existing_student.student_name}</a>',
				title="Số điện thoại trùng",
			)

	def _validate_unique_email(self):
		if not self.email:
			return
		existing = frappe.db.get_value(
			"CRM Contact",
			{"email": self.email, "name": ("!=", self.name or "")},
			["name", "full_name"],
			as_dict=True,
		)
		if existing:
			frappe.throw(
				f"Email <b>{self.email}</b> đã tồn tại trong liên hệ "
				f'<a href="/crm/contacts/{existing.name}">{existing.full_name}</a>',
				title="Email trùng",
			)
		existing_student = frappe.db.get_value(
			"CRM Student",
			{"email": self.email, "name": ("!=", self.student or "")},
			["name", "student_name"],
			as_dict=True,
		)
		if existing_student:
			frappe.throw(
				f"Email <b>{self.email}</b> đã tồn tại ở học sinh "
				f'<a href="/crm/crm-students/{existing_student.name}">{existing_student.student_name}</a>',
				title="Email trùng",
			)

	def _normalize_shared_fields(self):
		if isinstance(self.phone, str):
			self.phone = self.phone.strip()
		if isinstance(self.email, str):
			self.email = self.email.strip().lower()

	def _sync_fields_from_student_if_blank(self):
		if not self.student:
			return

		student_values = frappe.db.get_value(
			"CRM Student",
			self.student,
			[
				"student_name",
				"phone",
				"email",
				"high_school",
				"province",
				"major",
				"aspiration",
				"source",
				"admission_year",
				"branch",
				"enrollment_status",
			],
			as_dict=True,
		) or {}
		field_map = {
			"full_name": student_values.get("student_name"),
			"phone": student_values.get("phone"),
			"email": student_values.get("email"),
			"high_school": student_values.get("high_school"),
			"province": student_values.get("province"),
			"major": student_values.get("major"),
			"aspiration": student_values.get("aspiration"),
			"source": student_values.get("source"),
			"admission_year": student_values.get("admission_year"),
			"branch": student_values.get("branch"),
			"enrollment_status": student_values.get("enrollment_status"),
		}
		for fieldname, value in field_map.items():
			if not self.get(fieldname) and value:
				self.set(fieldname, value)

	def _create_student_at_milestone(self):
		"""Contain the retired Contact milestone writer.

		CRM Contact is a post-conversion relationship and is no longer an intake
		target. A Contact milestone must be handled by an explicit, authorized
		Student command after the conversion contract is available; silently
		creating a Student here would bypass identity, cycle, receipt and scope
		checks.
		"""
		return


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as _scoped

	return _scoped("CRM Contact", user=user)


def has_permission(doc, user=None, permission_type=None):
	from crm.fcrm.permissions import has_permission as _scoped

	return _scoped(doc, user=user, permission_type=permission_type)
