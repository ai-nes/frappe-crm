"""Append-only historical geography snapshots for Student 360."""

from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime

_SERVICE_FLAG = "student_geography_snapshot_service"
_GEO_FIELDS = ("province", "ward", "high_school")


class CRMStudentGeographySnapshot(Document):
	"""Preserve the geography context that was true at a Student change."""

	def before_insert(self):
		if not getattr(frappe.flags, _SERVICE_FLAG, False):
			frappe.throw(
				"Student geography snapshots must be recorded by the Student command hook.",
				frappe.PermissionError,
			)
		self.snapshot_id = self.snapshot_id or frappe.generate_hash(length=32)
		self.captured_at = self.captured_at or now_datetime()
		self.source = (self.source or "student_save").strip()[:140]

	def validate(self):
		if not self.student:
			frappe.throw("A geography snapshot requires a Student.", frappe.ValidationError)
		if not self.captured_at:
			frappe.throw("A geography snapshot requires captured_at.", frappe.ValidationError)
		if not any(self.get(field) for field in _GEO_FIELDS):
			frappe.throw("A geography snapshot requires at least one geography value.", frappe.ValidationError)
		if not self.is_new():
			frappe.throw("Student geography snapshots are append-only.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Student geography snapshots are append-only.", frappe.PermissionError)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as student_conditions

	condition = student_conditions("CRM Lead", user=user)
	if condition is None:
		return None
	if condition == "1=0":
		return "1=0"
	return (
		"`tabCRM Student Geography Snapshot`.`student` in "
		"(select `tabCRM Lead`.`name` from `tabCRM Lead` where (" + condition + "))"
	)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	if (permission_type or ptype) == "create":
		return bool(getattr(frappe.flags, _SERVICE_FLAG, False))
	return bool(doc.get("student") and frappe.has_permission("CRM Lead", "read", doc.student, user=user))


def snapshot_student_geography(doc, method=None):
	"""Capture initial/current geography only when the Student geography changes."""
	before = doc.get_doc_before_save()
	if before is not None and all(before.get(field) == doc.get(field) for field in _GEO_FIELDS):
		return
	if not any(doc.get(field) for field in _GEO_FIELDS):
		return
	flags = frappe.flags
	previous = getattr(flags, _SERVICE_FLAG, False)
	setattr(flags, _SERVICE_FLAG, True)
	try:
		frappe.get_doc(
			{
				"doctype": "CRM Student Geography Snapshot",
				"student": doc.name,
				"captured_at": now_datetime(),
				"province": doc.get("province"),
				"ward": doc.get("ward"),
				"high_school": doc.get("high_school"),
				"source": "student_save",
				"change_reason": "initial_capture" if before is None else "geography_changed",
			}
		).insert(ignore_permissions=True)
	finally:
		setattr(flags, _SERVICE_FLAG, previous)
