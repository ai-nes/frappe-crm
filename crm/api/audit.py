"""Read-only audit history APIs for CRM Student records."""

import json
from typing import Any

import frappe
from frappe import _

STUDENT_DOCTYPE = "CRM Student"
DEFAULT_PAGE_LENGTH = 50
MAX_PAGE_LENGTH = 100


def _parse_pagination(value: int | str | None, default: int, fieldname: str, minimum: int = 0) -> int:
	try:
		parsed = default if value in (None, "") else int(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be an integer.").format(fieldname), frappe.ValidationError)

	if parsed < minimum:
		frappe.throw(_("{0} must be at least {1}.").format(fieldname, minimum), frappe.ValidationError)

	return parsed


def _owner_details(owner: str | None) -> tuple[str | None, str | None]:
	if not owner:
		return None, None
	return owner, frappe.get_cached_value("User", owner, "full_name") or owner


def _field_map() -> dict[str, dict[str, str | None]]:
	return {
		field.fieldname: {"label": field.label, "options": field.options}
		for field in frappe.get_meta(STUDENT_DOCTYPE).fields
	}


def _version_logs(student: str) -> list[dict[str, Any]]:
	fields = _field_map()
	versions = frappe.db.get_all(
		"Version",
		filters={"ref_doctype": STUDENT_DOCTYPE, "docname": student},
		fields=["name", "data", "owner", "creation"],
		order_by="creation desc, name desc",
		limit_page_length=0,
	)
	logs = []

	for version in versions:
		try:
			payload = json.loads(version.data or "{}")
		except (TypeError, ValueError, json.JSONDecodeError):
			continue

		changed = payload.get("changed")
		if not isinstance(changed, list):
			continue

		owner, owner_full_name = _owner_details(version.owner)
		for index, change in enumerate(changed):
			if not isinstance(change, (list, tuple)) or len(change) < 3:
				continue

			fieldname, old_value, new_value = change[:3]
			field = fields.get(fieldname)
			if not field or (old_value in (None, "") and new_value in (None, "")):
				continue

			if old_value in (None, ""):
				change_type = "added"
			elif new_value in (None, ""):
				change_type = "removed"
			else:
				change_type = "changed"

			logs.append(
				{
					"event_id": f"{version.name}:{index}",
					"action": "updated",
					"change_type": change_type,
					"doctype": STUDENT_DOCTYPE,
					"docname": student,
					"fieldname": fieldname,
					"field_label": field.get("label") or fieldname,
					"old_value": old_value,
					"new_value": new_value,
					"owner": owner,
					"owner_full_name": owner_full_name,
					"occurred_at": version.creation,
					"source": "Version",
					"source_name": version.name,
				}
			)

	return logs


def _creation_log(student: str) -> dict[str, Any]:
	doc = frappe.db.get_value(STUDENT_DOCTYPE, student, ["creation", "owner"], as_dict=True)
	owner, owner_full_name = _owner_details(doc.owner)
	return {
		"event_id": f"creation:{STUDENT_DOCTYPE}:{student}",
		"action": "created",
		"change_type": None,
		"doctype": STUDENT_DOCTYPE,
		"docname": student,
		"fieldname": None,
		"field_label": None,
		"old_value": None,
		"new_value": None,
		"owner": owner,
		"owner_full_name": owner_full_name,
		"occurred_at": doc.creation,
		"source": "Document",
		"source_name": student,
	}


def _deletion_logs(student: str) -> list[dict[str, Any]]:
	deleted_documents = frappe.db.get_all(
		"Deleted Document",
		filters={"deleted_doctype": STUDENT_DOCTYPE, "deleted_name": student},
		fields=["name", "owner", "creation", "restored"],
		order_by="creation desc, name desc",
		limit_page_length=0,
	)
	logs = []

	for deleted in deleted_documents:
		owner, owner_full_name = _owner_details(deleted.owner)
		logs.append(
			{
				"event_id": f"deletion:{deleted.name}",
				"action": "deleted",
				"change_type": None,
				"doctype": STUDENT_DOCTYPE,
				"docname": student,
				"fieldname": None,
				"field_label": None,
				"old_value": None,
				"new_value": None,
				"owner": owner,
				"owner_full_name": owner_full_name,
				"occurred_at": deleted.creation,
				"source": "Deleted Document",
				"source_name": deleted.name,
				"restored": bool(deleted.restored),
			}
		)

	return logs


@frappe.whitelist()
def get_student_audit_logs(
	student: str,
	start: int | str | None = 0,
	page_length: int | str | None = DEFAULT_PAGE_LENGTH,
) -> dict[str, Any]:
	"""Return immutable create/update/delete history for one CRM Student."""
	if not student or not frappe.db.exists(STUDENT_DOCTYPE, student):
		frappe.throw(_("Student not found"), frappe.DoesNotExistError)

	if not frappe.has_permission(STUDENT_DOCTYPE, "read", student):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = _parse_pagination(start, 0, "start")
	page_length = _parse_pagination(page_length, DEFAULT_PAGE_LENGTH, "page_length", minimum=1)
	page_length = min(page_length, MAX_PAGE_LENGTH)

	logs = [
		_creation_log(student),
		*_version_logs(student),
		*_deletion_logs(student),
	]
	logs.sort(key=lambda log: (str(log["occurred_at"] or ""), str(log["event_id"])), reverse=True)

	return {
		"student": student,
		"logs": logs[start : start + page_length],
		"total": len(logs),
		"start": start,
		"page_length": page_length,
		"read_only": True,
	}
