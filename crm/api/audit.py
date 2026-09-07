"""Read-only audit history APIs for CRM Student records."""

import json
from typing import Any

import frappe
from frappe import _

from crm.fcrm.student_reference import canonical_student, lead_for_student

STUDENT_DOCTYPE = "CRM Lead"
DEFAULT_PAGE_LENGTH = 50
MAX_PAGE_LENGTH = 100

FIELD_AUDIT_METADATA = {
	"enrollment_status": {"event_type": "status_changed", "category": "status"},
	"lifecycle_stage": {"event_type": "lifecycle_changed", "category": "lifecycle"},
	"student_stage": {"event_type": "student_stage_changed", "category": "status"},
	"processing_status": {"event_type": "processing_status_changed", "category": "processing"},
	"resolution": {"event_type": "resolution_changed", "category": "processing"},
	"resolution_reason": {"event_type": "resolution_reason_changed", "category": "processing"},
	"assigned_to": {"event_type": "assignment_changed", "category": "assignment"},
	"owner_staff": {"event_type": "assignment_changed", "category": "assignment"},
	"owning_team": {"event_type": "team_changed", "category": "assignment"},
	"owning_pool": {"event_type": "pool_changed", "category": "assignment"},
	"converted_student": {"event_type": "conversion_changed", "category": "conversion"},
	"converted_at": {"event_type": "conversion_changed", "category": "conversion"},
	"conversion_status": {"event_type": "conversion_changed", "category": "conversion"},
}


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


def _field_map(doctype: str = STUDENT_DOCTYPE) -> dict[str, dict[str, str | None]]:
	return {
		field.fieldname: {"label": field.label, "options": field.options}
		for field in frappe.get_meta(doctype).fields
	}


def _version_logs(student: str, doctype: str = STUDENT_DOCTYPE) -> list[dict[str, Any]]:
	fields = _field_map(doctype)
	versions = frappe.db.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": student},
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

			field_metadata = FIELD_AUDIT_METADATA.get(
				fieldname,
				{"event_type": "field_changed", "category": "data"},
			)
			logs.append(
				{
					"event_id": f"{version.name}:{index}",
					"action": "updated",
					"change_type": change_type,
					"doctype": doctype,
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
					"event_type": field_metadata["event_type"],
					"category": field_metadata["category"],
				}
			)

	return logs


def _creation_log(student: str, doctype: str = STUDENT_DOCTYPE) -> dict[str, Any]:
	doc = frappe.db.get_value(doctype, student, ["creation", "owner"], as_dict=True)
	owner, owner_full_name = _owner_details(doc.owner)
	return {
		"event_id": f"creation:{doctype}:{student}",
		"action": "created",
		"change_type": None,
		"doctype": doctype,
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
		"event_type": "record_created",
		"category": "record",
	}


def _deletion_logs(student: str, doctype: str = STUDENT_DOCTYPE) -> list[dict[str, Any]]:
	deleted_documents = frappe.db.get_all(
		"Deleted Document",
		filters={"deleted_doctype": doctype, "deleted_name": student},
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
				"doctype": doctype,
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
				"event_type": "record_deleted",
				"category": "record",
			}
		)

	return logs


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except Exception:
		return False


def _display_value(doctype: str, value: Any, label_field: str) -> Any:
	if value in (None, ""):
		return value
	try:
		return frappe.db.get_value(doctype, value, label_field) or value
	except Exception:
		return value


def _business_log(
	*,
	event_id: str,
	docname: str,
	fieldname: str | None,
	field_label: str | None,
	old_value: Any,
	new_value: Any,
	owner: str | None,
	occurred_at: Any,
	source: str,
	source_name: str,
	event_type: str,
	category: str,
	reason: str | None = None,
	metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
	owner_id, owner_full_name = _owner_details(owner)
	log = {
		"event_id": event_id,
		"action": "updated",
		"change_type": "changed" if old_value not in (None, "") else "added",
		"doctype": STUDENT_DOCTYPE,
		"docname": docname,
		"fieldname": fieldname,
		"field_label": field_label,
		"old_value": old_value,
		"new_value": new_value,
		"owner": owner_id,
		"owner_full_name": owner_full_name,
		"occurred_at": occurred_at,
		"source": source,
		"source_name": source_name,
		"event_type": event_type,
		"category": category,
	}
	if reason not in (None, ""):
		log["reason"] = reason
	if metadata:
		log["metadata"] = metadata
	return log


def _status_change_logs(student: str) -> list[dict[str, Any]]:
	if not frappe.db.exists(STUDENT_DOCTYPE, student):
		return []
	doc = frappe.get_doc(STUDENT_DOCTYPE, student)
	logs = []
	for index, row in enumerate(doc.get("status_change_log") or []):
		from_code = row.get("from")
		to_code = row.get("to")
		is_initial_status = index == 0 and from_code not in (None, "") and to_code in (None, "")
		if to_code in (None, "") and not is_initial_status:
			continue
		row_name = row.get("name") or f"{student}:status:{index}"
		logs.append(
			_business_log(
				event_id=f"status:{row_name}",
				docname=student,
				fieldname="enrollment_status",
				field_label="Enrollment Status",
				old_value=None
				if is_initial_status
				else _display_value("CRM Enrollment Status", from_code, "display_name"),
				new_value=_display_value("CRM Enrollment Status", to_code or from_code, "display_name"),
				owner=row.get("log_owner") or doc.get("owner"),
				occurred_at=row.get("to_date") or row.get("from_date") or doc.get("modified"),
				source="Status Change Log",
				source_name=row_name,
				event_type="status_initialized" if is_initial_status else "status_changed",
				category="status",
				metadata={
					"old_code": None if is_initial_status else from_code,
					"new_code": to_code or from_code,
					"duration_seconds": row.get("duration"),
				},
			)
		)
	return logs


def _assignment_logs(student: str) -> list[dict[str, Any]]:
	if not frappe.db.exists(STUDENT_DOCTYPE, student):
		return []
	doc = frappe.get_doc(STUDENT_DOCTYPE, student)
	logs = []
	for index, row in enumerate(doc.get("assignment_log") or []):
		from_staff = row.get("from_staff")
		to_staff = row.get("to_staff")
		if from_staff in (None, "") and to_staff in (None, ""):
			continue
		row_name = row.get("name") or f"{student}:assignment:{index}"
		logs.append(
			_business_log(
				event_id=f"assignment:{row_name}",
				docname=student,
				fieldname="assigned_to",
				field_label="Assigned To",
				old_value=_display_value("CRM Staff", from_staff, "full_name"),
				new_value=_display_value("CRM Staff", to_staff, "full_name"),
				owner=row.get("changed_by") or doc.get("owner"),
				occurred_at=row.get("changed_at") or doc.get("modified"),
				source="Assignment Log",
				source_name=row_name,
				event_type="assignment_changed",
				category="assignment",
				reason=row.get("reason"),
				metadata={"auto_routed": bool(row.get("auto_routed"))},
			)
		)
	return logs


def _optional_event_logs(student: str) -> list[dict[str, Any]]:
	logs: list[dict[str, Any]] = []
	if _table_exists("CRM Student Lifecycle Event"):
		try:
			rows = frappe.get_all(
				"CRM Student Lifecycle Event",
				filters={"student": student},
				fields=[
					"name",
					"event_id",
					"from_stage",
					"to_stage",
					"transition_kind",
					"actor",
					"reason",
					"occurred_at",
				],
				order_by="occurred_at desc, name desc",
				limit_page_length=0,
			)
		except frappe.PermissionError:
			rows = []
		for row in rows:
			source_name = row.get("event_id") or row.get("name")
			logs.append(
				_business_log(
					event_id=f"lifecycle:{source_name}",
					docname=student,
					fieldname="lifecycle_stage",
					field_label="Lifecycle Stage",
					old_value=row.get("from_stage"),
					new_value=row.get("to_stage"),
					owner=row.get("actor"),
					occurred_at=row.get("occurred_at"),
					source="Lifecycle Event",
					source_name=source_name,
					event_type="lifecycle_changed",
					category="lifecycle",
					reason=row.get("reason"),
					metadata={"transition_kind": row.get("transition_kind")},
				)
			)

	if _table_exists("CRM Student Ownership Event"):
		try:
			rows = frappe.get_all(
				"CRM Student Ownership Event",
				filters={"student": student},
				fields=[
					"name",
					"event_id",
					"event_type",
					"prior_owner_staff",
					"next_owner_staff",
					"prior_owning_team",
					"next_owning_team",
					"prior_owning_pool",
					"next_owning_pool",
					"actor",
					"reason",
					"event_at",
				],
				order_by="event_at desc, name desc",
				limit_page_length=0,
			)
		except frappe.PermissionError:
			rows = []
		for row in rows:
			source_name = row.get("event_id") or row.get("name")
			logs.append(
				_business_log(
					event_id=f"ownership:{source_name}",
					docname=student,
					fieldname="owner_staff",
					field_label="Owner / Team / Pool",
					old_value=_display_value("CRM Staff", row.get("prior_owner_staff"), "full_name"),
					new_value=_display_value("CRM Staff", row.get("next_owner_staff"), "full_name"),
					owner=row.get("actor"),
					occurred_at=row.get("event_at"),
					source="Ownership Event",
					source_name=source_name,
					event_type="ownership_changed",
					category="assignment",
					reason=row.get("reason"),
					metadata={
						"event_type": row.get("event_type"),
						"old_team": row.get("prior_owning_team"),
						"new_team": row.get("next_owning_team"),
						"old_pool": row.get("prior_owning_pool"),
						"new_pool": row.get("next_owning_pool"),
					},
				)
			)

	if _table_exists("CRM Student Outcome"):
		try:
			rows = frappe.get_all(
				"CRM Student Outcome",
				filters={"student": student},
				fields=[
					"name",
					"event_id",
					"outcome_code",
					"continuity_kind",
					"next_action",
					"actor",
					"occurred_at",
				],
				order_by="occurred_at desc, name desc",
				limit_page_length=0,
			)
		except frappe.PermissionError:
			rows = []
		for row in rows:
			source_name = row.get("event_id") or row.get("name")
			logs.append(
				_business_log(
					event_id=f"outcome:{source_name}",
					docname=student,
					fieldname="outcome_code",
					field_label="Outcome",
					old_value=None,
					new_value=row.get("outcome_code"),
					owner=row.get("actor"),
					occurred_at=row.get("occurred_at"),
					source="Outcome Event",
					source_name=source_name,
					event_type="outcome_recorded",
					category="outcome",
					metadata={
						"continuity_kind": row.get("continuity_kind"),
						"next_action": row.get("next_action"),
					},
				)
			)

	return logs


def get_audit_logs_for_document(
	docname: str,
	*,
	doctype: str = STUDENT_DOCTYPE,
	include_creation: bool = True,
	include_deletion: bool = True,
) -> list[dict[str, Any]]:
	"""Build the additive audit projection used by Student and Lead readers."""
	logs: list[dict[str, Any]] = []
	if include_creation:
		logs.append(_creation_log(docname, doctype))
	logs.extend(_version_logs(docname, doctype))
	if doctype == STUDENT_DOCTYPE:
		logs.extend(_status_change_logs(docname))
		logs.extend(_assignment_logs(docname))
		logs.extend(_optional_event_logs(docname))
	if include_deletion:
		logs.extend(_deletion_logs(docname, doctype))
	logs.sort(key=lambda log: (str(log["occurred_at"] or ""), str(log["event_id"])), reverse=True)
	return logs


@frappe.whitelist()
def get_student_audit_logs(
	student: str,
	start: int | str | None = 0,
	page_length: int | str | None = DEFAULT_PAGE_LENGTH,
) -> dict[str, Any]:
	"""Return immutable create/update/delete history for one CRM Student.

	Audit rows are still recorded against the legacy CRM Lead projection, so a
	canonical CRM Student ID is resolved to its source Lead before reading the
	immutable history.
	"""
	requested_student = str(student or "").strip()
	canonical_id = canonical_student(requested_student)
	audit_docname = lead_for_student(canonical_id) if canonical_id else requested_student
	if not audit_docname or not frappe.db.exists(STUDENT_DOCTYPE, audit_docname):
		frappe.throw(_("Student not found"), frappe.DoesNotExistError)

	if canonical_id:
		allowed = frappe.has_permission("CRM Student", "read", canonical_id)
	else:
		allowed = frappe.has_permission(STUDENT_DOCTYPE, "read", audit_docname)
	if not allowed:
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	start = _parse_pagination(start, 0, "start")
	page_length = _parse_pagination(page_length, DEFAULT_PAGE_LENGTH, "page_length", minimum=1)
	page_length = min(page_length, MAX_PAGE_LENGTH)

	logs = get_audit_logs_for_document(audit_docname)

	return {
		"student": requested_student,
		"logs": logs[start : start + page_length],
		"total": len(logs),
		"start": start,
		"page_length": page_length,
		"read_only": True,
	}


@frappe.whitelist()
def get_lead_audit_logs(
	lead_id: str,
	start: int | str | None = 0,
	page_length: int | str | None = DEFAULT_PAGE_LENGTH,
) -> dict[str, Any]:
	"""Return the read-only audit history for one CRM Lead."""
	result = get_student_audit_logs(lead_id, start=start, page_length=page_length)
	return {**result, "lead_id": result["student"]}
