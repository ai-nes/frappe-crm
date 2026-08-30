"""Append-only privacy-right request contract for Student 360."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

REQUEST_TYPES = frozenset({"access", "rectification", "erasure", "restriction", "objection", "withdraw_consent"})
STATUSES = frozenset({"open", "in_progress", "completed", "rejected"})


class CRMStudentPrivacyRequest(Document):
	_IMMUTABLE_FIELDS = (
		"student", "contact", "request_type", "requested_at", "requested_by", "details",
		"resolution", "resolved_at", "resolved_by", "evidence_reference",
	)

	def _from_command(self):
		return bool(getattr(self.flags, "student_privacy_command", False))

	def validate(self):
		if self.request_type not in REQUEST_TYPES:
			frappe.throw(_("Privacy request type is invalid."), frappe.ValidationError)
		if self.status not in STATUSES:
			frappe.throw(_("Privacy request status is invalid."), frappe.ValidationError)
		if self.status == "completed" and (not self.resolution or not self.resolved_at or not self.resolved_by):
			frappe.throw(_("Completed privacy requests require resolution evidence and actor."), frappe.ValidationError)
		if self.is_new():
			if not self._from_command():
				frappe.throw(_("Privacy requests may only be created by the privacy command."))
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if any(self.get(fieldname) != before.get(fieldname) for fieldname in self._IMMUTABLE_FIELDS) and not self._from_command():
			frappe.throw(_("Privacy request facts are immutable."), frappe.PermissionError)
		if self.status != before.status and not self._from_command():
			frappe.throw(_("Privacy request state changes must use the privacy command."), frappe.PermissionError)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False
	permission_type = permission_type or ptype
	if permission_type in {"create", "write", "delete"}:
		roles = set(frappe.get_roles(user or frappe.session.user))
		return bool(
			(user or frappe.session.user) == "Administrator"
			or "System Manager" in roles
			or ("Admissions Director" in roles and frappe.has_permission("CRM Student", "write", student, user=user))
		)
	return bool(frappe.has_permission("CRM Student", "read", student, user=user))


def on_trash(doc, method=None):
	frappe.throw("Privacy requests are audit records and cannot be deleted.", frappe.PermissionError)


def get_permission_query_conditions(user=None):
	if not user:
		user = frappe.session.user
	from crm.fcrm.permissions import get_permission_query_conditions as student_conditions

	condition = student_conditions("CRM Student", user=user)
	if condition is None:
		return None
	if condition == "1=0":
		return "1=0"
	return "`tabCRM Student Privacy Request`.student in (select `tabCRM Student`.name from `tabCRM Student` where ({0}))".format(condition)
