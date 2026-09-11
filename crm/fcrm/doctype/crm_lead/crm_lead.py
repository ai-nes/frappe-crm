import json
import re
import uuid

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from crm.fcrm.campaign_source import sync_campaign_source
from crm.fcrm.conversion_readiness import conversion_readiness
from crm.fcrm.lead_code import (
	is_valid_lead_code,
	lead_code_from_name,
	lead_code_year,
	next_lead_code,
)
from crm.fcrm.lead_processing import PROCESSING_STATUSES, RESOLUTIONS, SERVICE_FLAG
from crm.fcrm.permissions import derive_owner_fields, derive_unassigned_owning_team
from crm.fcrm.student_reference import next_hs_code
from crm.fcrm.utils.geo_resolver import (
	resolve_high_school_strict,
	resolve_province,
	resolve_ward,
)

_CURRENT_GRADES = frozenset({"10", "11", "12", "post_exam"})
_STUDY_STAGES = frozenset({"grade_10", "grade_11", "grade_12_h1", "grade_12_h2", "post_exam"})
_STUDY_STAGE_GRADES = {
	"grade_10": "10",
	"grade_11": "11",
	"grade_12_h1": "12",
	"grade_12_h2": "12",
	"post_exam": "post_exam",
}
_CONVERSION_POTENTIALS = frozenset({"High", "Medium", "Low", "Unknown"})


class CRMLead(Document):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		# Frappe's _validate_links() runs before before_insert/before_save/validate
		# and throws its own generic error for any Link field holding free-text
		# input (e.g. high_school/province/ward from a Data Import row), before our
		# resolvers ever get a chance to run. We disable it here and re-run it
		# ourselves at the end of validate(), once geo fields are resolved.
		self.flags.ignore_links = True

	def autoname(self):
		"""Use the single HS identifier for new Lead intake records."""
		self.name = next_hs_code(self.get("admission_year"))

	def before_insert(self):
		self.lead_id = uuid.uuid4().hex
		# The code is server-managed; ignore any client/import value.
		self.lead_code = None
		self.processing_status = "NEW"
		self.resolution = "PENDING"
		self.matched_student = None
		self._set_defaults()
		self._normalize_phone_fields()
		self._resolve_geo()

	def after_insert(self):
		# Lead.name is available only after Frappe has assigned the HS identifier.
		# Keep the explicit lead_code field aligned with that single identifier.
		self._ensure_lead_code()
		frappe.db.set_value("CRM Lead", self.name, "lead_code", self.lead_code, update_modified=False)

	def before_save(self):
		before = self.get_doc_before_save()
		if before and before.get("lead_code") and self.get("lead_code") != before.get("lead_code"):
			frappe.throw(
				_("Lead Code is immutable after creation."),
				frappe.ValidationError,
			)
		if before and not (
			getattr(frappe.flags, "student_ownership_service", False)
			or getattr(frappe.flags, "lead_ownership_service", False)
		):
			ownership_fields = ("assigned_to", "owner_staff", "owning_team", "owning_pool")
			if any(before.get(field) != self.get(field) for field in ownership_fields):
				frappe.throw(
					_("Lead ownership changes must use the ownership command."),
					title=_("Ownership command required"),
				)
		if before and not getattr(frappe.flags, SERVICE_FLAG, False):
			processing_fields = (
				"processing_status",
				"resolution",
				"resolution_reason",
				"matched_student",
			)
			if any(before.get(field) != self.get(field) for field in processing_fields):
				frappe.throw(
					_("Lead processing changes must use the processing command."),
					frappe.PermissionError,
					title=_("Processing command required"),
				)
		self._normalize_phone_fields()
		self._resolve_geo()
		if self.cohort_end_year:
			self.cohort_start_year = int(self.cohort_end_year) - 3
		if self.get("lead_code") and not is_valid_lead_code(self.lead_code):
			frappe.throw(_("Student ID must match HS-YYYY-REGION-NNNNNN."), frappe.ValidationError)

	def validate(self):
		sync_campaign_source(self)
		self._validate_processing_contract()
		self._validate_phone_format()
		self._validate_conversion_potential()
		self._validate_segments()
		self._validate_current_grade()
		self._validate_study_stage()
		self._resolve_geo()
		self._validate_high_school_format()
		self._update_conversion_readiness()
		if (
			getattr(frappe.flags, "student_intake_service", False)
			or getattr(frappe.flags, "student_ownership_service", False)
			or not self.get_doc_before_save()
		):
			self._derive_owner_fields()
		if getattr(frappe.flags, "student_ownership_service", False) or getattr(
			frappe.flags, "lead_ownership_service", False
		):
			self._log_assignment_change()
		self.flags.ignore_links = False
		self._validate_links()

	def _validate_processing_contract(self):
		status = str(self.get("processing_status") or "NEW").strip().upper()
		resolution = str(self.get("resolution") or "PENDING").strip().upper()
		if status not in PROCESSING_STATUSES:
			frappe.throw(_("Invalid Lead processing status."), frappe.ValidationError)
		if resolution not in RESOLUTIONS:
			frappe.throw(_("Invalid Lead resolution."), frappe.ValidationError)
		if status == "NEW" and resolution != "PENDING":
			frappe.throw(_("A NEW Lead must have PENDING resolution."), frappe.ValidationError)
		if status == "PROCESSING" and resolution != "PENDING":
			frappe.throw(_("A Lead in PROCESSING must have PENDING resolution."), frappe.ValidationError)
		if status in {"PROCESSED", "ASSIGNED"} and resolution not in {"PENDING", "MATCHED", "CREATED"}:
			frappe.throw(
				_("A processed or assigned Lead must have a pending processing result."),
				frappe.ValidationError,
			)

	def _update_conversion_readiness(self):
		"""Keep the Lead's pre-conversion readiness projection server-managed."""
		readiness = conversion_readiness(self)
		if self.meta.has_field("conversion_blockers"):
			self.conversion_blockers = json.dumps(readiness["blockers"], ensure_ascii=False)

	def _derive_owner_fields(self):
		if self.assigned_to:
			self.owner_staff, self.owning_team = derive_owner_fields(self.assigned_to)
			return
		self.owner_staff = None
		if not self.owning_team:
			self.owning_team = derive_unassigned_owning_team(frappe.session.user)

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
				"auto_routed": int(bool(getattr(frappe.flags, "lead_ownership_auto_routed", False))),
				"reason": getattr(frappe.flags, "lead_ownership_reason", None)
				or self.status_change_reason,
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

	def _validate_conversion_potential(self):
		value = self.get("conversion_potential")
		if value and value not in _CONVERSION_POTENTIALS:
			frappe.throw(
				_("Conversion potential must be High, Medium, Low, or Unknown."),
				frappe.ValidationError,
			)

	def _validate_segments(self):
		value = self.get("segments")
		if not value:
			return
		if isinstance(value, str):
			try:
				value = frappe.parse_json(value)
			except (TypeError, ValueError):
				frappe.throw(_("Segments must be a JSON array."), frappe.ValidationError)
		if not isinstance(value, list) or any(
			not isinstance(item, str) or not item.strip() for item in value
		):
			frappe.throw(_("Segments must be a JSON array of non-empty strings."), frappe.ValidationError)
		self.segments = json.dumps(list(dict.fromkeys(item.strip() for item in value)), ensure_ascii=False)

	def _validate_current_grade(self):
		current_grade = self.get("current_grade")
		if current_grade and current_grade not in _CURRENT_GRADES:
			frappe.throw(
				_("Current grade must be 10, 11, 12, or post_exam."),
				frappe.ValidationError,
			)

	def _validate_study_stage(self):
		study_stage = self.get("study_stage")
		if study_stage and study_stage not in _STUDY_STAGES:
			frappe.throw(
				_("Study stage must be grade_10, grade_11, grade_12_h1, grade_12_h2, or post_exam."),
				frappe.ValidationError,
			)
		current_grade = self.get("current_grade")
		if study_stage and current_grade and _STUDY_STAGE_GRADES[study_stage] != current_grade:
			frappe.throw(
				_("Study stage {0} is inconsistent with current grade {1}.").format(
					study_stage, current_grade
				),
				frappe.ValidationError,
			)

	def _set_defaults(self):
		if not self.admission_year:
			current_year = str(frappe.utils.now_datetime().year)
			if frappe.db.exists("CRM Admission Year", current_year):
				self.admission_year = current_year
		if not self.branch:
			default_branch = frappe.db.get_value("CRM Campus", {"is_default": 1}, "name")
			if default_branch:
				self.branch = default_branch

	def _ensure_lead_code(self):
		if self.get("lead_code"):
			return
		mirrored_code = lead_code_from_name(self.name)
		if mirrored_code:
			self.lead_code = mirrored_code
			return
		year = lead_code_year(
			self.get("admission_year"),
			self.get("creation"),
			frappe.utils.now_datetime().year,
		)
		code = next_lead_code(year)
		while frappe.db.exists("CRM Lead", {"lead_code": code, "name": ["!=", self.name]}):
			code = next_lead_code(year)
		self.lead_code = code

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
		if isinstance(self.other_email, str):
			self.other_email = self.other_email.strip().lower()
		if isinstance(self.id_number, str):
			self.id_number = self.id_number.strip()

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Lead Code",
				"type": "Data",
				"key": "lead_code",
				"width": "12rem",
			},
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
				"label": "Processing Status",
				"type": "Data",
				"key": "processing_status",
				"width": "10rem",
			},
			{
				"label": "Resolution",
				"type": "Data",
				"key": "resolution",
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
				"label": "Source",
				"type": "Link",
				"key": "source",
				"options": "CRM Lead Source",
				"width": "10rem",
			},
			{
				"label": "Campaign",
				"type": "Link",
				"key": "campaign",
				"options": "CRM Campaign",
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
			"student_name",
			"phone",
			"email",
			"processing_status",
			"resolution",
			"assigned_to",
			"source",
			"campaign",
			"modified",
		]
		return {"columns": columns, "rows": rows}


@frappe.whitelist()
def convert_to_contact(
	student_name,
	expected_lifecycle_revision=None,
	idempotency_key=None,
	correlation_id=None,
	target_student=None,
):
	"""Retained route for old clients; it cannot bypass the conversion command."""
	return _convert_to_student(
		student_name,
		expected_lifecycle_revision,
		idempotency_key,
		correlation_id,
		target_student,
	)


@frappe.whitelist()
def convert_to_student(
	student_name,
	expected_lifecycle_revision=None,
	idempotency_key=None,
	correlation_id=None,
	target_student=None,
):
	"""Clear-named Lead -> Student route for new clients."""
	return _convert_to_student(
		student_name,
		expected_lifecycle_revision,
		idempotency_key,
		correlation_id,
		target_student,
	)


def _convert_to_student(
	student_name,
	expected_lifecycle_revision=None,
	idempotency_key=None,
	correlation_id=None,
	target_student=None,
):
	"""Delegate both route names to the server-owned conversion command."""
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
		target_student=target_student,
	)


@frappe.whitelist()
def create_from_contact(contact):
	# Contact is post-conversion identity data. Creating an admissions Student
	# from it bypasses identity/cycle resolution, review, pool selection, and
	# command receipts; the canonical intake service is the only allowed writer.
	frappe.throw(
		_("Creating a Student from Contact is retired; use the Student intake command."),
		frappe.PermissionError,
	)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as _scoped

	return _scoped("CRM Lead", user=user)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	from crm.fcrm.permissions import has_permission as _scoped

	return _scoped(doc, user=user, permission_type=permission_type, ptype=ptype)
