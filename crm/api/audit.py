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


def _unique_references(references: list[tuple[str, str]]) -> list[tuple[str, str]]:
	return list(dict.fromkeys((doctype, name) for doctype, name in references if doctype and name))


def _readable_references(references: list[tuple[str, str]]) -> list[tuple[str, str]]:
	readable = []
	for doctype, name in _unique_references(references):
		try:
			if frappe.has_permission(doctype, "read", name):
				readable.append((doctype, name))
		except (frappe.DoesNotExistError, frappe.PermissionError):
			continue
	return readable


def _related_document_references(docname: str, doctype: str) -> list[tuple[str, str]]:
	"""Return the primary record and its Lead/Student compatibility record."""
	references = [(doctype, docname)]
	if doctype == "CRM Lead" and frappe.db.exists("CRM Lead", docname):
		linked_student = (
			frappe.db.get_value("CRM Lead", docname, ["converted_student", "student"], as_dict=True) or {}
		)
		student = (
			linked_student.get("converted_student")
			or linked_student.get("student")
			or frappe.db.get_value("CRM Student", {"source_lead": docname}, "name")
			or frappe.db.get_value("CRM Student", {"student": docname}, "name")
		)
		if student and frappe.db.exists("CRM Student", student):
			references.append(("CRM Student", student))
	elif doctype == "CRM Student" and frappe.db.exists("CRM Student", docname):
		linked_lead = (
			frappe.db.get_value("CRM Student", docname, ["source_lead", "student"], as_dict=True) or {}
		)
		lead = linked_lead.get("source_lead") or linked_lead.get("student")
		if lead and frappe.db.exists("CRM Lead", lead):
			references.append(("CRM Lead", lead))
	return _unique_references(references)


def _safe_get_list(doctype: str, *, filters=None, fields=None, order_by=None) -> list[dict[str, Any]]:
	if not _table_exists(doctype):
		return []
	try:
		available_fields = {field.fieldname for field in frappe.get_meta(doctype).fields}
	except Exception:
		available_fields = set()
	available_fields.update(
		{
			"name",
			"owner",
			"creation",
			"modified",
			"modified_by",
			"parent",
			"parenttype",
			"parentfield",
			"idx",
		}
	)
	filters = filters or {}
	if any(field not in available_fields for field in filters):
		return []
	selected_fields = [field for field in (fields or ["name"]) if field in available_fields]
	if "name" not in selected_fields:
		selected_fields.insert(0, "name")
	selected_order_by = order_by
	if order_by:
		order_fields = [clause.strip().split()[0] for clause in order_by.split(",") if clause.strip()]
		if any(field not in available_fields for field in order_fields):
			selected_order_by = "creation desc, name desc"
	try:
		return (
			frappe.get_list(
				doctype,
				filters=filters,
				fields=selected_fields,
				order_by=selected_order_by,
				limit_page_length=0,
			)
			or []
		)
	except (frappe.PermissionError, frappe.DoesNotExistError):
		return []


def _rows_for_references(
	doctype: str,
	references: list[tuple[str, str]],
	fields: list[str],
	order_by: str = "creation desc, name desc",
) -> list[dict[str, Any]]:
	try:
		available_fields = {field.fieldname for field in frappe.get_meta(doctype).fields}
	except Exception:
		return []
	reference_name_field = next(
		(fieldname for fieldname in ("reference_name", "reference_docname") if fieldname in available_fields),
		None,
	)
	if not reference_name_field or "reference_doctype" not in available_fields:
		return []
	rows: list[dict[str, Any]] = []
	for reference_doctype, reference_name in _unique_references(references):
		rows.extend(
			_safe_get_list(
				doctype,
				filters={
					"reference_doctype": reference_doctype,
					reference_name_field: reference_name,
				},
				fields=fields,
				order_by=order_by,
			)
		)
	return list({str(row.get("name")): row for row in rows if row.get("name")}.values())


def _rows_for_field_values(
	doctype: str,
	fieldname: str,
	values: set[str],
	fields: list[str],
	order_by: str = "creation desc, name desc",
) -> list[dict[str, Any]]:
	if not values:
		return []
	return _safe_get_list(
		doctype,
		filters={fieldname: ["in", sorted(values)]},
		fields=fields,
		order_by=order_by,
	)


def _related_log(
	*,
	event_id: str,
	action: str,
	doctype: str,
	docname: str,
	owner: str | None,
	occurred_at: Any,
	source: str,
	source_name: str,
	event_type: str,
	category: str,
	content: str | None = None,
	subject: str | None = None,
	metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
	owner_id, owner_full_name = _owner_details(owner)
	log = {
		"event_id": event_id,
		"action": action,
		"change_type": None,
		"doctype": doctype,
		"docname": docname,
		"fieldname": None,
		"field_label": None,
		"old_value": None,
		"new_value": None,
		"owner": owner_id,
		"owner_full_name": owner_full_name,
		"occurred_at": occurred_at,
		"source": source,
		"source_name": source_name,
		"event_type": event_type,
		"category": category,
	}
	if content not in (None, ""):
		log["content"] = content
	if subject not in (None, ""):
		log["subject"] = subject
	if metadata:
		log["metadata"] = metadata
	return log


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
	doctype: str = STUDENT_DOCTYPE,
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
		"doctype": doctype,
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


def _status_change_logs(student: str, doctype: str = STUDENT_DOCTYPE) -> list[dict[str, Any]]:
	if not frappe.db.exists(doctype, student):
		return []
	doc = frappe.get_doc(doctype, student)
	logs = []
	for index, row in enumerate(doc.get("status_change_log") or []):
		from_code = row.get("from")
		to_code = row.get("to")
		row_name = row.get("name") or f"{student}:status:{index}"
		is_initial_status = index == 0 and from_code not in (None, "")
		if is_initial_status:
			logs.append(
				_business_log(
					event_id=f"status-initial:{row_name}",
					doctype=doctype,
					docname=student,
					fieldname="enrollment_status",
					field_label="Enrollment Status",
					old_value=None,
					new_value=_display_value("CRM Enrollment Status", from_code, "display_name"),
					owner=row.get("log_owner") or doc.get("owner"),
					occurred_at=row.get("from_date") or doc.get("creation"),
					source="Status Change Log",
					source_name=row_name,
					event_type="status_initialized",
					category="status",
					metadata={
						"old_code": None,
						"new_code": from_code,
						"duration_seconds": None,
					},
				)
			)
		if to_code in (None, ""):
			continue
		logs.append(
			_business_log(
				event_id=f"status:{row_name}",
				doctype=doctype,
				docname=student,
				fieldname="enrollment_status",
				field_label="Enrollment Status",
				old_value=_display_value("CRM Enrollment Status", from_code, "display_name"),
				new_value=_display_value("CRM Enrollment Status", to_code, "display_name"),
				owner=row.get("log_owner") or doc.get("owner"),
				occurred_at=row.get("to_date") or row.get("from_date") or doc.get("modified"),
				source="Status Change Log",
				source_name=row_name,
				event_type="status_changed",
				category="status",
				metadata={
					"old_code": from_code,
					"new_code": to_code,
					"duration_seconds": row.get("duration"),
				},
			)
		)
	return logs


def _assignment_logs(student: str, doctype: str = STUDENT_DOCTYPE) -> list[dict[str, Any]]:
	if not frappe.db.exists(doctype, student):
		return []
	doc = frappe.get_doc(doctype, student)
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
				doctype=doctype,
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


def _comment_logs(references: list[tuple[str, str]]) -> list[dict[str, Any]]:
	rows = _rows_for_references(
		"Comment",
		references,
		[
			"name",
			"comment_type",
			"reference_doctype",
			"reference_name",
			"content",
			"comment_email",
			"owner",
			"creation",
			"modified",
		],
	)
	return [
		_related_log(
			event_id=f"comment:{row['name']}",
			action="created",
			doctype=row.get("reference_doctype") or STUDENT_DOCTYPE,
			docname=row.get("reference_name") or "",
			owner=row.get("owner"),
			occurred_at=row.get("creation") or row.get("modified"),
			source="Comment",
			source_name=row["name"],
			event_type="comment_added",
			category="comment",
			content=row.get("content"),
			metadata={
				"comment_type": row.get("comment_type"),
				"comment_email": row.get("comment_email"),
			},
		)
		for row in rows
	]


def _communication_link_names(references: list[tuple[str, str]]) -> list[str]:
	if not _table_exists("Communication Link"):
		return []
	names: list[str] = []
	for reference_doctype, reference_name in _unique_references(references):
		rows = _safe_get_list(
			"Communication Link",
			filters={"link_doctype": reference_doctype, "link_name": reference_name},
			fields=["parent"],
			order_by="creation desc, parent desc",
		)
		names.extend(str(row.get("parent")) for row in rows if row.get("parent"))
	return list(dict.fromkeys(names))


def _communication_logs(references: list[tuple[str, str]]) -> list[dict[str, Any]]:
	rows = _rows_for_references(
		"Communication",
		references,
		[
			"name",
			"communication_type",
			"communication_medium",
			"subject",
			"content",
			"sender",
			"sender_full_name",
			"recipients",
			"cc",
			"bcc",
			"communication_date",
			"sent_or_received",
			"delivery_status",
			"read_by_recipient",
			"reference_doctype",
			"reference_name",
			"owner",
			"creation",
			"modified",
		],
	)
	linked_names = _communication_link_names(references)
	if linked_names:
		rows.extend(
			_safe_get_list(
				"Communication",
				filters={"name": ["in", linked_names]},
				fields=[
					"name",
					"communication_type",
					"communication_medium",
					"subject",
					"content",
					"sender",
					"sender_full_name",
					"recipients",
					"cc",
					"bcc",
					"communication_date",
					"sent_or_received",
					"delivery_status",
					"read_by_recipient",
					"reference_doctype",
					"reference_name",
					"owner",
					"creation",
					"modified",
				],
				order_by="creation desc, name desc",
			)
		)
	rows = list({str(row.get("name")): row for row in rows if row.get("name")}.values())
	logs = []
	for row in rows:
		metadata = {
			key: row.get(key)
			for key in (
				"communication_type",
				"communication_medium",
				"sender",
				"recipients",
				"cc",
				"bcc",
				"sent_or_received",
				"delivery_status",
				"read_by_recipient",
			)
			if row.get(key) not in (None, "")
		}
		logs.append(
			_related_log(
				event_id=f"communication:{row['name']}",
				action="created",
				doctype=row.get("reference_doctype") or STUDENT_DOCTYPE,
				docname=row.get("reference_name") or "",
				owner=row.get("owner") or row.get("sender"),
				occurred_at=row.get("communication_date") or row.get("creation"),
				source="Communication",
				source_name=row["name"],
				event_type="communication_recorded",
				category="communication",
				content=row.get("content"),
				subject=row.get("subject"),
				metadata=metadata,
			)
		)
	return logs


def _call_log_names(references: list[tuple[str, str]]) -> list[str]:
	if not _table_exists("Call Log"):
		return []
	names: list[str] = []
	for reference_doctype, reference_name in _unique_references(references):
		direct_rows = _safe_get_list(
			"Call Log",
			filters={"reference_doctype": reference_doctype, "reference_docname": reference_name},
			fields=["name"],
			order_by="creation desc, name desc",
		)
		names.extend(str(row.get("name")) for row in direct_rows if row.get("name"))
		if _table_exists("Dynamic Link"):
			linked_rows = _safe_get_list(
				"Dynamic Link",
				filters={
					"link_doctype": reference_doctype,
					"link_name": reference_name,
					"parenttype": "Call Log",
				},
				fields=["parent"],
				order_by="creation desc, parent desc",
			)
			names.extend(str(row.get("parent")) for row in linked_rows if row.get("parent"))
	return list(dict.fromkeys(names))


def _call_linked_names(references: list[tuple[str, str]], link_doctype: str) -> set[str]:
	call_names = _call_log_names(references)
	if not call_names or not _table_exists("Dynamic Link"):
		return set()
	rows = _safe_get_list(
		"Dynamic Link",
		filters={
			"parent": ["in", call_names],
			"parenttype": "Call Log",
			"link_doctype": link_doctype,
		},
		fields=["link_name"],
		order_by="creation desc, link_name desc",
	)
	return {str(row["link_name"]) for row in rows if row.get("link_name")}


def _call_logs(references: list[tuple[str, str]]) -> list[dict[str, Any]]:
	names = _call_log_names(references)
	if not names:
		return []
	rows = _safe_get_list(
		"Call Log",
		filters={"name": ["in", names]},
		fields=[
			"name",
			"caller",
			"receiver",
			"from",
			"to",
			"duration",
			"start_time",
			"end_time",
			"status",
			"type",
			"recording_url",
			"telephony_medium",
			"medium",
			"note",
			"reference_doctype",
			"reference_docname",
			"owner",
			"creation",
			"modified",
		],
		order_by="start_time desc, creation desc, name desc",
	)
	logs = []
	for row in rows:
		direction = "incoming" if str(row.get("type") or "").lower() == "incoming" else "outgoing"
		logs.append(
			_related_log(
				event_id=f"call:{row['name']}",
				action="created",
				doctype=row.get("reference_doctype") or STUDENT_DOCTYPE,
				docname=row.get("reference_docname") or "",
				owner=row.get("owner") or row.get("caller") or row.get("receiver"),
				occurred_at=row.get("start_time") or row.get("creation"),
				source="Call Log",
				source_name=row["name"],
				event_type="call_logged",
				category="call",
				content=f"Cuộc gọi {'đến' if direction == 'incoming' else 'đi'} — {row.get('status') or 'Chưa rõ trạng thái'}.",
				metadata={
					"direction": direction,
					"type": row.get("type"),
					"status": row.get("status"),
					"caller": row.get("caller"),
					"receiver": row.get("receiver"),
					"from": row.get("from"),
					"to": row.get("to"),
					"duration": row.get("duration"),
					"end_time": row.get("end_time"),
					"recording_url": row.get("recording_url"),
					"telephony_medium": row.get("telephony_medium"),
					"medium": row.get("medium"),
					"note": row.get("note"),
				},
			)
		)
	return logs


def _note_logs(
	references: list[tuple[str, str]], linked_names: set[str] | None = None
) -> list[dict[str, Any]]:
	rows = _rows_for_references(
		"FCRM Note",
		references,
		["name", "content", "reference_doctype", "reference_docname", "owner", "creation", "modified"],
		order_by="modified desc, creation desc, name desc",
	)
	if linked_names:
		rows.extend(
			_safe_get_list(
				"FCRM Note",
				filters={"name": ["in", sorted(linked_names)]},
				fields=[
					"name",
					"content",
					"reference_doctype",
					"reference_docname",
					"owner",
					"creation",
					"modified",
				],
				order_by="modified desc, creation desc, name desc",
			)
		)
	rows = list({str(row.get("name")): row for row in rows if row.get("name")}.values())
	return [
		_related_log(
			event_id=f"note:{row['name']}",
			action="updated"
			if row.get("modified") and row.get("modified") != row.get("creation")
			else "created",
			doctype=row.get("reference_doctype") or STUDENT_DOCTYPE,
			docname=row.get("reference_docname") or "",
			owner=row.get("owner"),
			occurred_at=row.get("modified") or row.get("creation"),
			source="FCRM Note",
			source_name=row["name"],
			event_type="note_updated"
			if row.get("modified") and row.get("modified") != row.get("creation")
			else "note_added",
			category="note",
			content=row.get("content"),
		)
		for row in rows
	]


def _task_logs(
	references: list[tuple[str, str]], linked_names: set[str] | None = None
) -> list[dict[str, Any]]:
	lead_names = {name for doctype, name in references if doctype == "CRM Lead"}
	student_names = {name for doctype, name in references if doctype == "CRM Student"}
	logs: list[dict[str, Any]] = []
	task_fields = [
		"name",
		"title",
		"description",
		"status",
		"priority",
		"assigned_to",
		"due_date",
		"student",
		"crm_student",
		"reference_doctype",
		"reference_docname",
		"owner",
		"creation",
		"modified",
	]
	if _table_exists("Task"):
		rows: list[dict[str, Any]] = []
		rows.extend(_rows_for_field_values("Task", "student", lead_names, task_fields))
		rows.extend(_rows_for_field_values("Task", "crm_student", student_names, task_fields))
		rows.extend(_rows_for_references("Task", references, task_fields))
		if linked_names:
			rows.extend(
				_safe_get_list(
					"Task",
					filters={"name": ["in", sorted(linked_names)]},
					fields=task_fields,
					order_by="creation desc, name desc",
				)
			)
		logs.extend(_task_row_logs("Task", rows))
	if _table_exists("CRM Action Item"):
		action_fields = [
			"name",
			"objective",
			"description",
			"state",
			"priority",
			"action_owner",
			"due_at",
			"outcome_code",
			"outcome_notes",
			"actor",
			"created_at",
			"completed_at",
			"student",
			"crm_student",
			"creation",
			"modified",
		]
		rows = []
		rows.extend(_rows_for_field_values("CRM Action Item", "student", student_names, action_fields))
		rows.extend(_rows_for_field_values("CRM Action Item", "crm_student", student_names, action_fields))
		logs.extend(_task_row_logs("CRM Action Item", rows))
	return logs


def _task_row_logs(doctype: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
	unique_rows = list({str(row.get("name")): row for row in rows if row.get("name")}.values())
	logs = []
	for row in unique_rows:
		logs.append(
			_related_log(
				event_id=f"task:{doctype}:{row['name']}",
				action="created",
				doctype=doctype,
				docname=row["name"],
				owner=row.get("owner")
				or row.get("actor")
				or row.get("action_owner")
				or row.get("assigned_to"),
				occurred_at=row.get("created_at") or row.get("creation"),
				source=doctype,
				source_name=row["name"],
				event_type="task_recorded",
				category="task",
				content=row.get("description") or row.get("objective") or row.get("title"),
				subject=row.get("title") or row.get("objective"),
				metadata={
					key: row.get(key)
					for key in (
						"status",
						"state",
						"priority",
						"assigned_to",
						"action_owner",
						"due_date",
						"due_at",
						"outcome_code",
						"outcome_notes",
						"completed_at",
					)
					if row.get(key) not in (None, "")
				},
			)
		)
	return logs


def _interaction_logs(references: list[tuple[str, str]]) -> list[dict[str, Any]]:
	student_names = {name for doctype, name in references if doctype == "CRM Student"}
	fields = [
		"name",
		"student",
		"crm_contact",
		"crm_student",
		"interaction_type",
		"interaction_datetime",
		"outcome",
		"channel",
		"direction",
		"summary",
		"notes",
		"reference_doctype",
		"reference_docname",
		"actor",
		"owner",
		"creation",
		"modified",
	]
	rows = _rows_for_references("CRM Interaction", references, fields)
	rows.extend(_rows_for_field_values("CRM Interaction", "student", student_names, fields))
	rows.extend(_rows_for_field_values("CRM Interaction", "crm_contact", student_names, fields))
	rows.extend(_rows_for_field_values("CRM Interaction", "crm_student", student_names, fields))
	rows = list({str(row.get("name")): row for row in rows if row.get("name")}.values())
	return [
		_related_log(
			event_id=f"interaction:{row['name']}",
			action="created",
			doctype=row.get("reference_doctype") or "CRM Student",
			docname=row.get("reference_docname") or row.get("student") or row.get("crm_student") or "",
			owner=row.get("actor") or row.get("owner"),
			occurred_at=row.get("interaction_datetime") or row.get("creation"),
			source="CRM Interaction",
			source_name=row["name"],
			event_type="interaction_recorded",
			category="interaction",
			content=row.get("summary") or row.get("notes"),
			subject=row.get("interaction_type"),
			metadata={
				key: row.get(key)
				for key in ("outcome", "channel", "direction")
				if row.get(key) not in (None, "")
			},
		)
		for row in rows
	]


def _attachment_logs(references: list[tuple[str, str]]) -> list[dict[str, Any]]:
	rows: list[dict[str, Any]] = []
	for reference_doctype, reference_name in _unique_references(references):
		rows.extend(
			_safe_get_list(
				"File",
				filters={"attached_to_doctype": reference_doctype, "attached_to_name": reference_name},
				fields=[
					"name",
					"file_name",
					"file_type",
					"file_url",
					"file_size",
					"is_private",
					"attached_to_doctype",
					"attached_to_name",
					"owner",
					"creation",
					"modified",
				],
				order_by="creation desc, name desc",
			)
		)
	rows = list({str(row.get("name")): row for row in rows if row.get("name")}.values())
	return [
		_related_log(
			event_id=f"file:{row['name']}",
			action="created",
			doctype=row.get("attached_to_doctype") or STUDENT_DOCTYPE,
			docname=row.get("attached_to_name") or "",
			owner=row.get("owner"),
			occurred_at=row.get("creation") or row.get("modified"),
			source="File",
			source_name=row["name"],
			event_type="attachment_added",
			category="attachment",
			content=row.get("file_name"),
			metadata={
				"file_name": row.get("file_name"),
				"file_type": row.get("file_type"),
				"file_url": row.get("file_url"),
				"file_size": row.get("file_size"),
				"is_private": bool(row.get("is_private")),
			},
		)
		for row in rows
	]


def _optional_event_logs(references: list[tuple[str, str]]) -> list[dict[str, Any]]:
	logs: list[dict[str, Any]] = []
	lead_names = {name for doctype, name in references if doctype == "CRM Lead"}
	student_names = {name for doctype, name in references if doctype == "CRM Student"}

	for row in _rows_for_field_values(
		"CRM Student Lifecycle Event",
		"student",
		student_names,
		[
			"name",
			"event_id",
			"student",
			"from_stage",
			"to_stage",
			"transition_kind",
			"actor",
			"reason",
			"occurred_at",
		],
		order_by="occurred_at desc, name desc",
	):
		source_name = row.get("event_id") or row.get("name")
		logs.append(
			_business_log(
				event_id=f"lifecycle:{source_name}",
				doctype="CRM Student",
				docname=row.get("student") or "",
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

	for row in _rows_for_field_values(
		"CRM Student Ownership Event",
		"student",
		lead_names,
		[
			"name",
			"event_id",
			"student",
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
	):
		source_name = row.get("event_id") or row.get("name")
		logs.append(
			_business_log(
				event_id=f"ownership:{source_name}",
				doctype="CRM Lead",
				docname=row.get("student") or "",
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

	for row in _rows_for_field_values(
		"CRM Student Outcome",
		"student",
		student_names,
		[
			"name",
			"event_id",
			"student",
			"outcome_code",
			"continuity_kind",
			"next_action",
			"actor",
			"occurred_at",
		],
		order_by="occurred_at desc, name desc",
	):
		source_name = row.get("event_id") or row.get("name")
		logs.append(
			_business_log(
				event_id=f"outcome:{source_name}",
				doctype="CRM Student",
				docname=row.get("student") or "",
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

	for row in _rows_for_field_values(
		"CRM Marketing Engagement",
		"student",
		lead_names,
		[
			"name",
			"student",
			"engagement_kind",
			"crm_campaign",
			"crm_event",
			"touched_at",
			"registered_at",
			"status",
			"actor",
			"creation",
		],
		order_by="creation desc, name desc",
	):
		kind = row.get("engagement_kind") or "engagement"
		logs.append(
			_business_log(
				event_id=f"engagement:{row.get('name')}",
				doctype="CRM Lead",
				docname=row.get("student") or "",
				fieldname="engagement",
				field_label="Marketing Engagement",
				old_value=None,
				new_value=row.get("crm_campaign") or row.get("crm_event") or kind,
				owner=row.get("actor"),
				occurred_at=row.get("touched_at") or row.get("registered_at") or row.get("creation"),
				source="Marketing Engagement",
				source_name=row.get("name") or "",
				event_type=f"{kind}_recorded",
				category="engagement",
				metadata={
					"engagement_kind": kind,
					"campaign": row.get("crm_campaign"),
					"event": row.get("crm_event"),
					"status": row.get("status"),
				},
			)
		)

	for row in _rows_for_field_values(
		"CRM Student SLA Event",
		"student",
		lead_names,
		["name", "event_id", "student", "event_type", "actor", "event_at", "creation"],
		order_by="event_at desc, name desc",
	):
		logs.append(
			_business_log(
				event_id=f"sla:{row.get('event_id') or row.get('name')}",
				doctype="CRM Lead",
				docname=row.get("student") or "",
				fieldname="sla_status",
				field_label="SLA",
				old_value=None,
				new_value=row.get("event_type"),
				owner=row.get("actor"),
				occurred_at=row.get("event_at") or row.get("creation"),
				source="SLA Event",
				source_name=row.get("event_id") or row.get("name") or "",
				event_type="sla_event_recorded",
				category="sla",
			)
		)

	for row in _rows_for_field_values(
		"CRM Student Decision Event",
		"student",
		student_names,
		[
			"name",
			"event_id",
			"student",
			"event_type",
			"actor",
			"occurred_at",
			"reason",
			"recommendation",
			"action",
		],
		order_by="occurred_at desc, name desc",
	):
		logs.append(
			_business_log(
				event_id=f"decision:{row.get('event_id') or row.get('name')}",
				doctype="CRM Student",
				docname=row.get("student") or "",
				fieldname="decision",
				field_label="Decision",
				old_value=None,
				new_value=row.get("event_type"),
				owner=row.get("actor"),
				occurred_at=row.get("occurred_at"),
				source="Decision Event",
				source_name=row.get("event_id") or row.get("name") or "",
				event_type="decision_recorded",
				category="decision",
				reason=row.get("reason"),
				metadata={"recommendation": row.get("recommendation"), "action": row.get("action")},
			)
		)

	for row in _rows_for_field_values(
		"CRM Contact Consent Event",
		"student",
		lead_names,
		["name", "student", "event_type", "occurred_at", "source", "created_by", "purpose", "scope", "note"],
		order_by="occurred_at desc, name desc",
	):
		logs.append(
			_business_log(
				event_id=f"consent:{row.get('name')}",
				doctype="CRM Lead",
				docname=row.get("student") or "",
				fieldname="privacy_status",
				field_label="Consent & Privacy",
				old_value=None,
				new_value=row.get("event_type"),
				owner=row.get("created_by"),
				occurred_at=row.get("occurred_at"),
				source="Consent Event",
				source_name=row.get("name") or "",
				event_type="consent_recorded",
				category="consent",
				metadata={
					"source": row.get("source"),
					"purpose": row.get("purpose"),
					"scope": row.get("scope"),
					"note": row.get("note"),
				},
			)
		)

	conversion_rows = _rows_for_field_values(
		"CRM Student Contact Conversion",
		"student",
		lead_names,
		["name", "student", "contact", "actor", "converted_at", "creation"],
		order_by="converted_at desc, name desc",
	)
	conversion_rows.extend(
		_rows_for_field_values(
			"CRM Student Contact Conversion",
			"contact",
			student_names,
			["name", "student", "contact", "actor", "converted_at", "creation"],
			order_by="converted_at desc, name desc",
		)
	)
	for row in list({str(row.get("name")): row for row in conversion_rows if row.get("name")}.values()):
		logs.append(
			_business_log(
				event_id=f"conversion:{row.get('name')}",
				doctype="CRM Student" if row.get("contact") else "CRM Lead",
				docname=row.get("contact") or row.get("student") or "",
				fieldname="converted_student",
				field_label="Student Conversion",
				old_value=None,
				new_value=row.get("contact") or row.get("student"),
				owner=row.get("actor"),
				occurred_at=row.get("converted_at") or row.get("creation"),
				source="Conversion Event",
				source_name=row.get("name") or "",
				event_type="conversion_completed",
				category="conversion",
			)
		)

	return logs


def get_audit_logs_for_document(
	docname: str,
	*,
	doctype: str = STUDENT_DOCTYPE,
	include_creation: bool = True,
	include_deletion: bool = True,
	related_references: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
	"""Build the additive audit projection used by Student and Lead readers."""
	references = _readable_references(related_references or _related_document_references(docname, doctype))
	logs: list[dict[str, Any]] = []
	for reference_doctype, reference_name in references:
		if include_creation:
			logs.append(_creation_log(reference_name, reference_doctype))
		logs.extend(_version_logs(reference_name, reference_doctype))
		if reference_doctype in {"CRM Lead", "CRM Student"}:
			logs.extend(_status_change_logs(reference_name, reference_doctype))
			logs.extend(_assignment_logs(reference_name, reference_doctype))
		if include_deletion:
			logs.extend(_deletion_logs(reference_name, reference_doctype))

	logs.extend(_optional_event_logs(references))
	logs.extend(_interaction_logs(references))
	logs.extend(_comment_logs(references))
	logs.extend(_communication_logs(references))
	call_logs = _call_logs(references)
	logs.extend(call_logs)
	call_note_names = {
		str(log.get("metadata", {}).get("note")) for log in call_logs if log.get("metadata", {}).get("note")
	}
	call_note_names.update(_call_linked_names(references, "FCRM Note"))
	note_logs = _note_logs(references, call_note_names)
	logs.extend(note_logs)
	task_logs = _task_logs(references, _call_linked_names(references, "Task"))
	logs.extend(task_logs)

	related_activity_references = _unique_references(
		references
		+ [
			(log["source"], log["source_name"])
			for log in logs
			if log.get("source")
			and log.get("source_name")
			and log["source"]
			in {
				"Comment",
				"Communication",
				"Call Log",
				"FCRM Note",
				"Task",
				"CRM Action Item",
				"CRM Interaction",
			}
		]
	)
	for related_doctype, related_name in related_activity_references:
		if (related_doctype, related_name) not in references:
			logs.extend(_version_logs(related_name, related_doctype))
			if include_deletion:
				logs.extend(_deletion_logs(related_name, related_doctype))
	logs.extend(_attachment_logs(related_activity_references))
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

	references = _related_document_references(audit_docname, STUDENT_DOCTYPE)
	if canonical_id and frappe.db.exists("CRM Student", canonical_id):
		references = _unique_references([*references, ("CRM Student", canonical_id)])
	logs = get_audit_logs_for_document(audit_docname, related_references=references)

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
