from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class CRMParentContactAuthority(Document):
	"""Append-only authorization evidence for Parent Contact actions."""

	_IMMUTABLE_FIELDS = (
		"student", "contact", "relationship_verified", "relationship_type",
		"decision_role", "decision_influence", "concerns", "lawful_basis",
		"allowed_channels", "effective_at", "expires_at", "proof_reference",
	)

	def before_insert(self):
		if not getattr(frappe.flags, "student_parent_context_service", False):
			frappe.throw(
				"Parent Contact Authority must be recorded through the Student 360 command.",
				frappe.PermissionError,
			)
		self.effective_at = self.effective_at or now_datetime()
		self.decision_role = self.decision_role or "Unknown"
		self.decision_influence = self.decision_influence or "Unknown"

	def validate(self):
		if not self.is_new():
			if not getattr(frappe.flags, "student_parent_context_service", False):
				frappe.throw("Parent Contact Authority is append-only.", frappe.PermissionError)
			before = self.get_doc_before_save()
			if before and any(self.get(field) != before.get(field) for field in self._IMMUTABLE_FIELDS):
				frappe.throw("Parent relationship facts are immutable; use a new authority record.", frappe.PermissionError)
		if self.decision_role not in {"Unknown", "Primary decision maker", "Influencer", "Information only"}:
			frappe.throw("Decision role is invalid.", frappe.ValidationError)
		if self.decision_influence not in {"Unknown", "High", "Medium", "Low"}:
			frappe.throw("Decision influence is invalid.", frappe.ValidationError)
		if not self.lawful_basis or not self.proof_reference:
			frappe.throw("lawful_basis and proof_reference are required.", frappe.ValidationError)
		if self.revoked_at and not self.revocation_evidence:
			raise ValueError("revocation evidence is required")

	def on_trash(self):
		frappe.throw("Parent Contact Authority is append-only.", frappe.PermissionError)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as student_conditions

	condition = student_conditions("CRM Student", user=user)
	if condition is None:
		return None
	if condition == "1=0":
		return "1=0"
	return "`tabCRM Parent Contact Authority`.student in (select `tabCRM Student`.name from `tabCRM Student` where ({0}))".format(condition)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False
	permission_type = permission_type or ptype
	if permission_type in {"create", "write", "delete"}:
		roles = set(frappe.get_roles(user or frappe.session.user))
		return bool((user or frappe.session.user) == "Administrator" or "System Manager" in roles or "Admissions Director" in roles)
	return bool(frappe.has_permission("CRM Student", "read", student, user=user))
