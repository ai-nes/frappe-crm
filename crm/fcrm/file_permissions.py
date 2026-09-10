"""Student attachment permission guard.

Files attached to a Student inherit the Student read scope.  Destructive or
visibility-changing operations require an admissions supervisor; unrelated
files keep Frappe's default permission behaviour.
"""

from __future__ import annotations

import frappe

from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_reference import canonical_student


def _student_attachment_target(doc):
	"""Return the permission target for a current or legacy Student attachment."""
	if not hasattr(doc, "get"):
		return None
	doctype = doc.get("attached_to_doctype")
	name = doc.get("attached_to_name")
	if doctype == "CRM Student":
		return "CRM Student", name
	if doctype == "CRM Lead":
		student = canonical_student(name)
		return ("CRM Student", student) if student else ("CRM Lead", name)
	return None


def before_insert(doc, method=None):
	"""Force every new Student attachment private at the trust boundary."""
	if _student_attachment_target(doc):
		doc.is_private = 1


def has_permission(doc, user=None, permission_type=None):
	target = _student_attachment_target(doc)
	if not target or not target[1]:
		return None
	target_doctype, student = target
	user = user or frappe.session.user
	if permission_type == "read":
		try:
			return bool(frappe.has_permission(target_doctype, "read", student, user=user))
		except Exception:
			return False
	roles = frappe.get_roles(user)
	capabilities = capabilities_for_roles(roles, administrator=user == "Administrator")
	if permission_type in {"write", "delete"}:
		return user == "Administrator" or "System Manager" in roles or "admissions.oversee" in capabilities
	if permission_type == "create":
		try:
			return bool(frappe.has_permission(target_doctype, "write", student, user=user))
		except Exception:
			return False
	return None
