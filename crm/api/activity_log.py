"""Read-only activity history for administrators."""

import json
from datetime import datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, get_datetime, now_datetime

from crm.api.session import get_session_role_flags

DEFAULT_PAGE_LENGTH = 50
MAX_PAGE_LENGTH = 100

MODULE_DOCTYPE_MAP = {
	"auth": [],
	"lead_student": ["CRM Lead", "CRM Student"],
	"segment": ["CRM Segment"],
	"campaign_nba": ["CRM Campaign", "CRM Action Item"],
	"permissions": ["User"],
}
MODULE_DOCTYPE_MAP["all"] = [doctype for module in MODULE_DOCTYPE_MAP.values() for doctype in module]

FIELD_SEVERITY_OVERRIDES = {
	("User", "roles"): "critical",
	("CRM Segment", "is_public"): "critical",
	("CRM Segment", "status"): "critical",
	("CRM Campaign", "status"): "critical",
	("CRM Lead", "owner_staff"): "critical",
	("CRM Lead", "owning_team"): "critical",
	("CRM Lead", "owning_pool"): "critical",
	("CRM Student", "owner_staff"): "critical",
}

PERMISSION_AUDIT_FIELDS = {"roles", "enabled"}

FIELD_AUDIT_METADATA = {
	"student_stage": {"event_type": "student_stage_changed", "category": "status"},
	"processing_status": {"event_type": "processing_status_changed", "category": "processing"},
	"resolution": {"event_type": "resolution_changed", "category": "processing"},
	"resolution_reason": {"event_type": "resolution_changed", "category": "processing"},
	"assigned_to": {"event_type": "assignment_changed", "category": "assignment"},
	"owner_staff": {"event_type": "assignment_changed", "category": "assignment"},
	"owning_team": {"event_type": "team_changed", "category": "assignment"},
	"owning_pool": {"event_type": "pool_changed", "category": "assignment"},
	"converted_student": {"event_type": "conversion_changed", "category": "conversion"},
	"converted_at": {"event_type": "conversion_changed", "category": "conversion"},
	"status": {"event_type": "status_changed", "category": "status"},
	"roles": {"event_type": "permissions_changed", "category": "permissions"},
	"enabled": {"event_type": "user_enabled_changed", "category": "permissions"},
}


def _parse_int(value: int | str | None, default: int, fieldname: str, minimum: int = 0) -> int:
	try:
		parsed = default if value in (None, "") else int(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be an integer.").format(fieldname), frappe.ValidationError)

	if parsed < minimum:
		frappe.throw(_("{0} must be at least {1}.").format(fieldname, minimum), frappe.ValidationError)
	return parsed


def _require_admin() -> None:
	"""Enforce the same admin control-plane policy as the existing CRM APIs."""
	if not get_session_role_flags()["is_system_manager"]:
		frappe.throw(_("Only administrators may view activity logs."), frappe.PermissionError)


def _date_range(start_date: str | datetime | None, end_date: str | datetime | None):
	end = get_datetime(end_date) if end_date else now_datetime()
	start = get_datetime(start_date) if start_date else add_days(end, -7)
	if start > end:
		frappe.throw(_("start_date must be before end_date."), frappe.ValidationError)

	# Date-only end values represent the whole calendar day in the UI.
	if end_date and len(str(end_date)) == 10:
		end = add_days(end, 1)
	return start, end


def _owner_details(owner: str | None) -> tuple[str | None, str | None]:
	if not owner:
		return None, None
	return owner, frappe.get_cached_value("User", owner, "full_name") or owner


def _field_map(doctype: str) -> dict[str, Any]:
	try:
		return {field.fieldname: field for field in frappe.get_meta(doctype).fields}
	except Exception:
		return {}


def _severity_for(doctype: str, fieldname: str | None, action: str = "updated") -> str:
	if action == "deleted":
		return "critical"
	return FIELD_SEVERITY_OVERRIDES.get((doctype, fieldname), "info")


def _field_metadata(doctype: str, fieldname: str) -> dict[str, str]:
	metadata = FIELD_AUDIT_METADATA.get(fieldname)
	if metadata and (doctype != "User" or fieldname in PERMISSION_AUDIT_FIELDS):
		return metadata
	return {"event_type": "field_changed", "category": "data"}


def _change_type(old_value: Any, new_value: Any) -> str:
	if old_value in (None, ""):
		return "added"
	if new_value in (None, ""):
		return "removed"
	return "changed"


def _actor_filter(actor: str | list[str] | None) -> list[Any] | None:
	if not actor:
		return None
	if isinstance(actor, list):
		return ["owner", "in", actor]
	return ["owner", "=", actor]


def _find_actor_ids(actor: str | None) -> list[str] | None:
	if not actor or not actor.strip():
		return None
	term = f"%{actor.strip()}%"
	return frappe.get_all(
		"User",
		or_filters=[["full_name", "like", term], ["name", "like", term]],
		pluck="name",
		limit_page_length=0,
	)


def _version_logs(doctypes: list[str], actor: str | list[str] | None, start, end) -> list[dict[str, Any]]:
	if not doctypes:
		return []
	filters: list[list[Any]] = [
		["ref_doctype", "in", doctypes],
		["creation", "between", [start, end]],
	]
	if actor:
		filters.append(_actor_filter(actor))
	versions = frappe.get_all(
		"Version",
		filters=filters,
		fields=["name", "ref_doctype", "docname", "data", "owner", "creation"],
		order_by="creation desc, name desc",
		limit_page_length=0,
	)
	logs = []
	for version in versions:
		try:
			changed = json.loads(version.data or "{}").get("changed", [])
		except (TypeError, ValueError, json.JSONDecodeError):
			continue
		if not isinstance(changed, list):
			continue
		fields = _field_map(version.ref_doctype)
		owner, owner_full_name = _owner_details(version.owner)
		for index, item in enumerate(changed):
			if not isinstance(item, (list, tuple)) or len(item) < 3:
				continue
			fieldname, old_value, new_value = item[:3]
			if version.ref_doctype == "User" and fieldname not in PERMISSION_AUDIT_FIELDS:
				continue
			field = fields.get(fieldname)
			if not field:
				continue
			logs.append(
				{
					"event_id": f"{version.name}:{index}",
					"action": "updated",
					"change_type": _change_type(old_value, new_value),
					"doctype": version.ref_doctype,
					"docname": version.docname,
					"fieldname": fieldname,
					"field_label": field.label or fieldname,
					"old_value": old_value,
					"new_value": new_value,
					"owner": owner,
					"owner_full_name": owner_full_name,
					"occurred_at": version.creation,
					"source": "Version",
					"source_name": version.name,
					**_field_metadata(version.ref_doctype, fieldname),
					"severity": _severity_for(version.ref_doctype, fieldname),
				}
			)
	return logs


def _deletion_logs(doctypes: list[str], actor: str | list[str] | None, start, end) -> list[dict[str, Any]]:
	if not doctypes or not frappe.db.table_exists("Deleted Document"):
		return []
	filters: list[list[Any]] = [
		["deleted_doctype", "in", doctypes],
		["creation", "between", [start, end]],
	]
	if actor:
		filters.append(_actor_filter(actor))
	deleted_documents = frappe.get_all(
		"Deleted Document",
		filters=filters,
		fields=["name", "deleted_doctype", "deleted_name", "owner", "creation", "restored"],
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
				"doctype": deleted.deleted_doctype,
				"docname": deleted.deleted_name,
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
				"severity": "critical",
			}
		)
	return logs


def _auth_activity_logs(actor: str | list[str] | None, start, end) -> list[dict[str, Any]]:
	if not frappe.db.table_exists("Activity Log"):
		return []
	filters: list[list[Any]] = [
		["operation", "in", ["Login", "Logout", "login", "logout"]],
		["creation", "between", [start, end]],
	]
	if actor:
		actor_filter = _actor_filter(actor)
		filters.append(["user", actor_filter[1], actor_filter[2]])
	rows = frappe.get_all(
		"Activity Log",
		filters=filters,
		fields=["name", "user", "operation", "creation", "status"],
		order_by="creation desc, name desc",
		limit_page_length=0,
	)
	logs = []
	for row in rows:
		owner, owner_full_name = _owner_details(row.user)
		operation = str(row.operation or "").lower()
		action = "created" if operation == "login" else "updated"
		logs.append(
			{
				"event_id": f"auth:{row.name}",
				"action": action,
				"change_type": None,
				"doctype": None,
				"docname": None,
				"fieldname": None,
				"field_label": None,
				"old_value": None,
				"new_value": row.status,
				"owner": owner,
				"owner_full_name": owner_full_name,
				"occurred_at": row.creation,
				"source": "Activity Log",
				"source_name": row.name,
				"event_type": f"{operation}_recorded",
				"category": "authentication",
				"severity": "info",
			}
		)
	return logs


def _tracked_for_module(doctypes: list[str]) -> bool:
	if not doctypes:
		return True
	for doctype in doctypes:
		try:
			if not frappe.get_meta(doctype).track_changes:
				return False
		except Exception:
			return False
	return True


@frappe.whitelist()
def get_activity_logs(
	module: str,
	actor: str | None = None,
	role: str | None = None,
	severity: str | None = None,
	start_date: str | None = None,
	end_date: str | None = None,
	start: int | str | None = 0,
	page_length: int | str | None = DEFAULT_PAGE_LENGTH,
) -> dict[str, Any]:
	"""Return administrator activity for one module.

	The role filter uses each user's current role membership; historical roles
	are not stored in Version and cannot be reconstructed from these sources.
	"""
	_require_admin()
	if module not in MODULE_DOCTYPE_MAP:
		frappe.throw(_("Unknown activity log module."), frappe.ValidationError)
	if severity not in (None, "", "info", "critical"):
		frappe.throw(_("Invalid activity log severity."), frappe.ValidationError)

	start = _parse_int(start, 0, "start")
	page_length = min(_parse_int(page_length, DEFAULT_PAGE_LENGTH, "page_length", 1), MAX_PAGE_LENGTH)
	from_date, to_date = _date_range(start_date, end_date)
	doctypes = MODULE_DOCTYPE_MAP[module]

	actor_ids = _find_actor_ids(actor)
	if role:
		role_actor_ids = frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "role": role},
			pluck="parent",
			limit_page_length=0,
		)
		actor_ids = (
			role_actor_ids if actor_ids is None else [user for user in actor_ids if user in role_actor_ids]
		)

	def collect_for(actor_id: str | None):
		logs = _version_logs(doctypes, actor_id, from_date, to_date)
		logs.extend(_deletion_logs(doctypes, actor_id, from_date, to_date))
		if module in ("auth", "all"):
			logs.extend(_auth_activity_logs(actor_id, from_date, to_date))
		return logs

	if (actor or role) and not actor_ids:
		logs = []
	elif actor_ids:
		logs = collect_for(actor_ids)
	else:
		logs = collect_for(actor)
	if severity:
		logs = [log for log in logs if log.get("severity") == severity]

	logs.sort(
		key=lambda log: (str(log.get("occurred_at") or ""), str(log.get("event_id") or "")), reverse=True
	)
	return {
		"logs": logs[start : start + page_length],
		"total": len(logs),
		"start": start,
		"page_length": page_length,
		"module": module,
		"tracked": _tracked_for_module(doctypes),
	}
