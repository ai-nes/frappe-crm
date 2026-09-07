import re

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

from crm.fcrm.lifecycle import enforce_lifecycle_change_policy, get_lifecycle_stage
from crm.fcrm.permissions import derive_owner_fields, derive_unassigned_owning_team
from crm.fcrm.utils.geo_resolver import resolve_high_school_strict, resolve_province

# Kept for the legacy anomaly report. Student creation itself is no longer
# milestone-gated: a Student may be created/imported independently.
MILESTONE_ENROLLMENT_STATUSES = {"CONFIRMED", "ENROLLED"}

CONVERSION_SERVICE_FLAG = "student_conversion_service"
MIGRATION_SERVICE_FLAG = "contact_migration_service"


class CRMStudent(Document):
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
		self._normalize_shared_fields()
		self._resolve_geo()
		# Student is an independent record and may be created/imported directly.
		# Routing only derives Student ownership; it never creates or updates a
		# CRM Lead.
		from crm.api.routing import route_new_lead

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
		self._validate_guarded_update()
		self._normalize_shared_fields()
		self._resolve_geo()

	def on_update(self):
		# Student updates stay on the Student record. No hook writes back to a
		# CRM Lead; the conversion command is the only one-time snapshot writer.
		return

	def validate(self):
		self._normalize_shared_fields()
		self._derive_owner_fields()
		self._derive_lifecycle_stage()
		self._log_assignment_change()
		self._validate_phone_format()
		self._resolve_geo()
		self._validate_high_school_format()
		self._track_sla_start()
		self.flags.ignore_links = False
		self._validate_links()

	def _is_service_write(self):
		return bool(
			getattr(frappe.flags, CONVERSION_SERVICE_FLAG, False)
			or getattr(frappe.flags, MIGRATION_SERVICE_FLAG, False)
		)

	def _validate_guarded_update(self):
		before = self.get_doc_before_save()
		if not before:
			return
		changed = {
			fieldname
			for fieldname in self.meta.get_valid_columns()
			if before.get(fieldname) != self.get(fieldname)
		}
		if "student" in changed:
			frappe.throw("CRM Student.student is a read-only legacy compatibility link.", frappe.PermissionError)
		if "student_identity" in changed:
			# Identity ownership can never be reassigned after it is set. A
			# conversion/migration may stamp a blank identity once.
			if before.get("student_identity") or not self._is_service_write():
				frappe.throw("CRM Student.student_identity is immutable.", frappe.PermissionError)

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

	def _normalize_shared_fields(self):
		if isinstance(self.phone, str):
			self.phone = self.phone.strip()
		if isinstance(self.email, str):
			self.email = self.email.strip().lower()

def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as _scoped

	return _scoped("CRM Student", user=user)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	from crm.fcrm.permissions import has_permission as _scoped

	return _scoped(doc, user=user, permission_type=permission_type, ptype=ptype)
