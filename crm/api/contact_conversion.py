"""Scoped read adapters for Student/Contact conversion history."""

from __future__ import annotations

import frappe

from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_contact_conversion import visible_conversion_history_page
from crm.fcrm.student_feature_flags import enabled


def _actor() -> str:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		frappe.throw("Authentication is required.", frappe.PermissionError)
	return actor


@frappe.whitelist()
def get_contact_conversion_history(contact: str, limit: int = 50, cursor: str | None = None):
	_actor()
	if not enabled("conversion_read"):
		return {
			"contact": contact,
			"history": [],
			"next_cursor": None,
			"redacted_count": 0,
			"read_enabled": False,
		}
	doc = frappe.get_doc("CRM Student", contact)
	if not doc.has_permission("read"):
		frappe.throw("You do not have permission to view this Contact.", frappe.PermissionError)
	page = visible_conversion_history_page(contact, limit=min(max(int(limit or 50), 1), 100), cursor=cursor)
	return {
		"contact": contact,
		"history": page["history"],
		"next_cursor": page["next_cursor"],
		"redacted_count": page["redacted_count"],
		"read_enabled": True,
	}


@frappe.whitelist()
def get_student_conversion_context(student: str):
	actor = _actor()
	doc = frappe.get_doc("CRM Lead", student)
	if not doc.has_permission("read"):
		frappe.throw("You do not have permission to view this Student.", frappe.PermissionError)
	read_enabled = enabled("conversion_read")
	write_enabled = enabled("conversion_write")
	roles = frappe.get_roles(actor)
	capabilities = capabilities_for_roles(roles, administrator=actor == "Administrator")
	stage = doc.get("lifecycle_stage") or "Lead"
	return {
		"student": student,
		"stage": stage,
		"revision": int(doc.get("lifecycle_revision") or 0),
		"can_convert": read_enabled and write_enabled and stage == "Enrolled" and ("conversion.execute" in capabilities or actor == "Administrator"),
		"read_enabled": read_enabled,
		"write_enabled": write_enabled,
	}
