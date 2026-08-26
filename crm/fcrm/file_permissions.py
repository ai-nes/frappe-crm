"""Student attachment permission guard.

Files attached to a Student inherit the Student read scope.  Destructive or
visibility-changing operations require an admissions supervisor; unrelated
files keep Frappe's default permission behaviour.
"""

from __future__ import annotations

import frappe

from crm.fcrm.role_policy import capabilities_for_roles


def before_insert(doc, method=None):
	"""Force every new Student attachment private at the trust boundary."""
	if doc.get("attached_to_doctype") == "CRM Student":
		doc.is_private = 1


def has_permission(doc, user=None, permission_type=None):
	student = doc.get("attached_to_name") if hasattr(doc, "get") and doc.get("attached_to_doctype") == "CRM Student" else None
	if not student:
		return None
	user = user or frappe.session.user
	if permission_type == "read":
		try:
			return bool(frappe.has_permission("CRM Student", "read", student, user=user))
		except Exception:
			return False
	roles = frappe.get_roles(user)
	capabilities = capabilities_for_roles(roles, administrator=user == "Administrator")
	if permission_type in {"write", "delete"}:
		return user == "Administrator" or "System Manager" in roles or "admissions.oversee" in capabilities
	if permission_type == "create":
		try:
			return bool(frappe.has_permission("CRM Student", "write", student, user=user))
		except Exception:
			return False
	return None
