"""Read-only relationship helpers for Student ↔ Contact conversion history.

The conversion junction is authoritative once present.  The legacy
``CRM Contact.student`` link is used only as a temporary compatibility fallback
for rows that have not been migrated yet.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import frappe

CONVERSION_DOCTYPE = "CRM Student Contact Conversion"


def _table_available() -> bool:
	try:
		return bool(frappe.db.table_exists(CONVERSION_DOCTYPE))
	except (AttributeError, TypeError):
		return False


def conversion_rows_for_student(student: str, *, limit: int = 100) -> list[dict[str, Any]]:
	if not student or not _table_available():
		return []
	return frappe.db.get_all(
		CONVERSION_DOCTYPE,
		filters={"student": student},
		fields=["name", "student", "student_identity", "case_key", "contact", "converted_at", "actor", "command_receipt"],
		order_by="converted_at asc, name asc",
		limit_page_length=limit,
		ignore_permissions=True,
	)


def conversion_rows_for_contact(contact: str, *, limit: int = 100, start: int = 0) -> list[dict[str, Any]]:
	if not contact or not _table_available():
		return []
	return frappe.db.get_all(
		CONVERSION_DOCTYPE,
		filters={"contact": contact},
		fields=["name", "student", "student_identity", "case_key", "contact", "converted_at", "actor", "command_receipt"],
		order_by="converted_at asc, name asc",
		limit_page_length=limit,
		limit_start=max(int(start or 0), 0),
		ignore_permissions=True,
	)


def contacts_for_student(student: str) -> list[str]:
	rows = conversion_rows_for_student(student)
	contacts = [row.get("contact") for row in rows if row.get("contact")]
	if contacts:
		return list(dict.fromkeys(contacts))
	legacy = frappe.db.get_value("CRM Contact", {"student": student}, "name")
	return [legacy] if legacy else []


def students_for_contact(contact: str) -> list[str]:
	rows = conversion_rows_for_contact(contact)
	students = [row.get("student") for row in rows if row.get("student")]
	if students:
		return list(dict.fromkeys(students))
	legacy = frappe.db.get_value("CRM Contact", contact, "student")
	return [legacy] if legacy else []


def contact_for_student(student: str, *, requested_contact: str | None = None) -> str | None:
	contacts = contacts_for_student(student)
	if requested_contact:
		return requested_contact if requested_contact in contacts else None
	return contacts[0] if len(contacts) == 1 else None


def contact_is_linked_to_student(contact: str, student: str) -> bool:
	if not contact or not student:
		return False
	rows = conversion_rows_for_contact(contact)
	if rows:
		return any(row.get("student") == student for row in rows)
	return frappe.db.get_value("CRM Contact", contact, "student") == student


def relationship_source(contact: str, student: str | None = None) -> str:
	rows = conversion_rows_for_contact(contact)
	if rows and (student is None or any(row.get("student") == student for row in rows)):
		return "junction"
	if frappe.db.get_value("CRM Contact", contact, "student") and (student is None or frappe.db.get_value("CRM Contact", contact, "student") == student):
		return "legacy"
	return "none"


def visible_conversion_history(contact: str, *, limit: int = 100) -> list[dict[str, Any]]:
	"""Return redacted history; each linked Student is permission-filtered."""
	return visible_conversion_history_page(contact, limit=limit)["history"]


def _encode_cursor(start: int) -> str:
	payload = json.dumps({"start": start}, separators=(",", ":")).encode()
	return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
	if not cursor:
		return 0
	try:
		padded = cursor + "=" * (-len(cursor) % 4)
		value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode()).get("start")
		start = int(value)
	except (TypeError, ValueError, KeyError, json.JSONDecodeError, UnicodeDecodeError):
		frappe.throw("Invalid conversion history cursor.", frappe.ValidationError)
	if start < 0 or start > 10000:
		frappe.throw("Invalid conversion history cursor.", frappe.ValidationError)
	return start


def visible_conversion_history_page(contact: str, *, limit: int = 100, cursor: str | None = None) -> dict[str, Any]:
	"""Return one bounded, permission-filtered history page and opaque cursor."""
	if not _table_available():
		return {"history": [], "next_cursor": None, "redacted_count": 0}
	limit = min(max(int(limit or 100), 1), 100)
	start = _decode_cursor(cursor)
	rows = conversion_rows_for_contact(contact, limit=limit + 1, start=start)
	visible = []
	redacted_count = 0
	for row in rows:
		student = row.get("student")
		try:
			allowed = bool(frappe.has_permission("CRM Student", "read", student))
		except Exception:
			allowed = False
		if allowed:
			visible.append(row)
		else:
			redacted_count += 1
			visible.append({"name": row.get("name"), "contact": contact, "redacted": True})
	has_more = len(visible) > limit
	return {
		"history": visible[:limit],
		"next_cursor": _encode_cursor(start + limit) if has_more else None,
		"redacted_count": redacted_count,
	}
