"""Permission-scoped overview API for the CTV Sale workspace.

The response is built from one report date and one server snapshot.  Every
source read goes through ``frappe.get_list`` so Student/Contact row-level
permissions are applied before any aggregate is calculated.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe

from crm.api.director_school_common import parse_limit, raise_api_error
from crm.fcrm.role_policy import resolve_compatibility_overlay, resolve_crm_profile

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
TREND_RANGES = {"7d", "30d"}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
DIRECT_INTERACTION_TYPES = {"outreach", "connected", "counseling"}
CONNECTED_OUTCOMES = {"captured", "resolved", "converted", "connected"}
TERMINAL_TASK_STATES = {"done", "canceled", "completed", "cancelled", "rejected", "superseded"}
MANAGER_PROFILES = {"lead_sales"}
MANAGER_OVERLAYS = {"team_leader"}

STUDENT_FIELDS = ["name", "student_name", "lifecycle_stage", "enrollment_status", "modified"]
CONTACT_FIELDS = ["name", "student", "readiness_level", "next_follow_up"]
INTERACTION_FIELDS = [
	"name",
	"student",
	"interaction_type",
	"interaction_datetime",
	"outcome",
	"source_verified",
	"creation",
]
TASK_FIELDS = [
	"name",
	"title",
	"description",
	"student",
	"priority",
	"status",
	"due_date",
	"modified",
	"creation",
]
ACTION_FIELDS = [
	"name",
	"legacy_generic_task",
	"student",
	"action",
	"action_type",
	"objective",
	"priority",
	"state",
	"due_at",
	"action_owner",
	"created_at",
	"modified",
	"completed_at",
]


@frappe.whitelist(methods=["GET"])
def get_ctv_sale_overview(
	date: str | None = None,
	trendRange: str = "7d",
	outcomeRange: str = "30d",
	timezone: str = DEFAULT_TIMEZONE,
	ctvId: str | None = None,
	priorityLimit: str | int = 3,
) -> dict[str, Any]:
	"""Return one consistent, permission-scoped CTV Sale dashboard snapshot."""
	access = _require_access()
	report_timezone = _parse_timezone(timezone)
	report_date = _parse_report_date(date, report_timezone)
	trend_range = _parse_range(trendRange, "trendRange")
	outcome_range = _parse_range(outcomeRange, "outcomeRange")
	priority_limit = parse_limit(priorityLimit, field="priorityLimit", minimum=1, maximum=10, default=3)
	target_staff = _resolve_target_staff(ctvId, access)
	as_of = _now(report_timezone)
	warnings: list[str] = []

	students = _load_students(target_staff, warnings)
	student_ids = [str(row.get("name")) for row in students if row.get("name")]
	student_names = {
		str(row.get("name")): str(row.get("student_name") or "Hồ sơ chưa đặt tên")
		for row in students
		if row.get("name")
	}
	contacts = _load_contacts(student_ids, warnings)
	interactions = _load_interactions(student_ids, warnings)
	tasks = _load_tasks(student_ids, warnings)
	for task in tasks:
		task["student_name"] = student_names.get(task.get("student_id"), "Hồ sơ chưa đặt tên")

	status = "available"
	if warnings:
		status = "unavailable" if not students and _has_warning(warnings, "students") else "partial"

	return {
		"meta": {
			"viewer": _viewer(target_staff, access["user"]),
			"date": report_date.isoformat(),
			"asOf": as_of.isoformat(timespec="seconds"),
			"timezone": getattr(report_timezone, "key", str(report_timezone)),
			"status": status,
			"warnings": warnings,
		},
		"kpis": _build_kpis(students, contacts, interactions, tasks),
		"tasks": _build_tasks(tasks, report_date, as_of, report_timezone, priority_limit),
		"studentStatus": _build_student_status(students, contacts, interactions),
		"contacts": {
			"trend": _build_contact_trend(interactions, report_date, trend_range, report_timezone),
			"outcomes": _build_contact_outcomes(interactions, report_date, outcome_range, report_timezone),
		},
	}


def _require_access() -> dict[str, Any]:
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		raise_api_error(
			"UNAUTHENTICATED",
			"Bạn cần đăng nhập để truy cập dữ liệu CTV Sale.",
			frappe.AuthenticationError,
			401,
		)
	if frappe.db.get_value("User", user, "enabled") not in (1, True, "1") and user != "Administrator":
		raise_api_error(
			"UNAUTHENTICATED",
			"Tài khoản không hoạt động.",
			frappe.AuthenticationError,
			401,
		)
	roles = set(frappe.get_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return {"user": user, "profile": "platform_superuser", "manager": True}

	profile = resolve_crm_profile(roles)
	overlay = resolve_compatibility_overlay(roles)
	if profile not in {"ctv_sale", "lead_sales"} and overlay not in {"sales_own", "team_leader"}:
		raise_api_error(
			"FORBIDDEN",
			"Bạn không có quyền truy cập tổng quan CTV Sale.",
			frappe.PermissionError,
			403,
		)
	return {
		"user": user,
		"profile": profile,
		"manager": profile in MANAGER_PROFILES or overlay in MANAGER_OVERLAYS or "System Manager" in roles,
	}


def _parse_timezone(value: Any) -> ZoneInfo:
	text = str(value or DEFAULT_TIMEZONE).strip()
	if not text or len(text) > 64:
		raise_api_error(
			"INVALID_QUERY", "Tham số timezone phải là IANA timezone hợp lệ.", frappe.ValidationError, 400
		)
	try:
		return ZoneInfo(text)
	except ZoneInfoNotFoundError:
		raise_api_error(
			"INVALID_QUERY", "Tham số timezone phải là IANA timezone hợp lệ.", frappe.ValidationError, 400
		)
	raise AssertionError("raise_api_error always raises")


def _parse_report_date(value: Any, timezone: ZoneInfo) -> date:
	if value in (None, ""):
		return _now(timezone).date()
	text = str(value).strip()
	try:
		parsed = datetime.strptime(text, "%Y-%m-%d").date()
	except (TypeError, ValueError):
		raise_api_error(
			"INVALID_QUERY", "Tham số date phải có định dạng YYYY-MM-DD.", frappe.ValidationError, 400
		)
	if parsed.isoformat() != text:
		raise_api_error(
			"INVALID_QUERY", "Tham số date phải có định dạng YYYY-MM-DD.", frappe.ValidationError, 400
		)
	return parsed


def _parse_range(value: Any, field: str) -> str:
	text = str(value or "").strip().lower() or ("7d" if field == "trendRange" else "30d")
	if text not in TREND_RANGES:
		raise_api_error("INVALID_QUERY", f"Tham số {field} phải là 7d hoặc 30d.", frappe.ValidationError, 400)
	return text


def _resolve_target_staff(ctv_id: Any, access: dict[str, Any]) -> dict[str, Any] | None:
	text = str(ctv_id or "").strip()
	staff_rows = _get_list(
		"CRM Staff",
		filters={"is_active": 1},
		fields=["name", "user", "full_name", "is_active"],
		limit_page_length=0,
		warnings=None,
	)
	by_id = {str(row.get("name")): dict(row) for row in staff_rows}
	by_user = {str(row.get("user")): dict(row) for row in staff_rows if row.get("user")}
	current = by_user.get(access["user"])
	if not text:
		return current
	if not access["manager"]:
		raise_api_error(
			"FORBIDDEN",
			"CTV Sale thông thường không được chọn CTV khác.",
			frappe.PermissionError,
			403,
		)
	if len(text) > 140:
		raise_api_error("INVALID_QUERY", "Tham số ctvId không hợp lệ.", frappe.ValidationError, 400)
	selected = by_id.get(text) or by_user.get(text)
	if not selected:
		raise_api_error(
			"CTV_NOT_FOUND", "Không tìm thấy CTV Sale đang hoạt động.", frappe.DoesNotExistError, 404
		)
	return selected


def _viewer(staff: dict[str, Any] | None, fallback_user: str) -> dict[str, str]:
	user = str((staff or {}).get("user") or fallback_user)
	display_name = (staff or {}).get("full_name")
	if not display_name:
		display_name = frappe.db.get_value("User", user, "full_name") or user
	return {"id": user, "displayName": str(display_name)}


def _load_students(target_staff: dict[str, Any] | None, warnings: list[str]) -> list[dict[str, Any]]:
	filters: dict[str, Any] = {"lifecycle_stage": ["!=", "Lost"]}
	if target_staff:
		filters["owner_staff"] = target_staff["name"]
	rows = _get_list(
		"CRM Student",
		filters=filters,
		fields=STUDENT_FIELDS,
		order_by="name asc",
		limit_page_length=0,
		warnings=warnings,
		warning_key="students",
	)
	return [dict(row) for row in rows]


def _load_contacts(student_ids: list[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not student_ids:
		return []
	return [
		dict(row)
		for row in _get_list(
			"CRM Contact",
			filters={"student": ["in", student_ids]},
			fields=CONTACT_FIELDS,
			order_by="name asc",
			limit_page_length=0,
			warnings=warnings,
			warning_key="contacts",
		)
	]


def _load_interactions(student_ids: list[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not student_ids:
		return []
	return [
		dict(row)
		for row in _get_list(
			"CRM Interaction",
			filters={"student": ["in", student_ids], "source_verified": 1},
			fields=INTERACTION_FIELDS,
			order_by="interaction_datetime asc, name asc",
			limit_page_length=0,
			warnings=warnings,
			warning_key="interactions",
		)
		if _is_direct_interaction(row)
	]


def _load_tasks(student_ids: list[str], warnings: list[str]) -> list[dict[str, Any]]:
	if not student_ids:
		return []
	action_rows = [
		dict(row)
		for row in _get_list(
			"CRM Action Item",
			filters={"student": ["in", student_ids]},
			fields=ACTION_FIELDS,
			order_by="due_at asc, name asc",
			limit_page_length=0,
			warnings=warnings,
			warning_key="action_items",
		)
	]
	migrated_task_ids = {
		str(row.get("legacy_generic_task")) for row in action_rows if row.get("legacy_generic_task")
	}
	generic_rows = [
		dict(row)
		for row in _get_list(
			"Task",
			filters={"student": ["in", student_ids]},
			fields=TASK_FIELDS,
			order_by="due_date asc, name asc",
			limit_page_length=0,
			warnings=warnings,
			warning_key="tasks",
		)
		if str(row.get("name")) not in migrated_task_ids
	]
	return [_normalize_action_task(row) for row in action_rows] + [
		_normalize_generic_task(row) for row in generic_rows
	]


def _get_list(
	doctype: str,
	*,
	filters: dict[str, Any],
	fields: list[str],
	limit_page_length: int,
	warnings: list[str] | None,
	warning_key: str | None = None,
	order_by: str | None = None,
) -> list[Any]:
	if not frappe.db.table_exists(doctype):
		if warnings is not None and warning_key:
			warnings.append(f"{warning_key}.source_unavailable")
		return []
	try:
		kwargs: dict[str, Any] = {
			"filters": filters,
			"fields": fields,
			"limit_page_length": limit_page_length,
		}
		if order_by:
			kwargs["order_by"] = order_by
		return list(frappe.get_list(doctype, **kwargs))
	except Exception:
		if warnings is not None and warning_key:
			warnings.append(f"{warning_key}.source_unavailable")
		return []


def _has_warning(warnings: list[str], key: str) -> bool:
	return any(item.startswith(f"{key}.") for item in warnings)


def _now(timezone: ZoneInfo) -> datetime:
	return datetime.now(timezone)


def _is_direct_interaction(row: dict[str, Any]) -> bool:
	interaction_type = str(row.get("interaction_type") or "").strip().casefold()
	return interaction_type in DIRECT_INTERACTION_TYPES


def _normalize_action_task(row: dict[str, Any]) -> dict[str, Any]:
	state = str(row.get("state") or "pending").strip().lower()
	status = (
		"done"
		if state == "completed"
		else "canceled"
		if state in TERMINAL_TASK_STATES
		else "in-progress"
		if state == "in-progress"
		else "todo"
	)
	action_type = str(row.get("action_type") or row.get("action") or "").strip()
	return {
		"id": f"CRM Action Item:{row.get('name')}",
		"student_id": str(row.get("student") or ""),
		"title": str(row.get("objective") or ""),
		"detail": str(row.get("objective") or ""),
		"task_type": _task_type(action_type, row.get("objective")),
		"task_type_label": _task_type_label(action_type, row.get("objective")),
		"priority": _priority(row.get("priority")),
		"status": status,
		"due": _coerce_datetime(row.get("due_at")),
		"completed": _coerce_datetime(row.get("completed_at")) if state == "completed" else None,
	}


def _normalize_generic_task(row: dict[str, Any]) -> dict[str, Any]:
	title = str(row.get("title") or "")
	detail = _plain_text(row.get("description")) or title
	status = str(row.get("status") or "Todo").strip().lower()
	return {
		"id": f"Task:{row.get('name')}",
		"student_id": str(row.get("student") or ""),
		"title": title,
		"detail": detail,
		"task_type": _task_type(title, detail),
		"task_type_label": _task_type_label(title, detail),
		"priority": _priority(row.get("priority")),
		"status": "done"
		if status == "done"
		else "canceled"
		if status == "canceled"
		else "in-progress"
		if status == "in progress"
		else "todo",
		"due": _coerce_datetime(row.get("due_date")),
		"completed": _coerce_datetime(row.get("modified")) if status == "done" else None,
	}


def _build_kpis(
	students: list[dict[str, Any]],
	contacts: list[dict[str, Any]],
	interactions: list[dict[str, Any]],
	tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
	student_ids = {str(row.get("name")) for row in students if row.get("name")}
	attempted_ids = {str(row.get("student")) for row in interactions if row.get("student")}
	transfer_ids = _transfer_ids(students, contacts)
	assigned = len(student_ids)
	uncontacted = len(student_ids - attempted_ids)
	follow_up_ids = {
		str(row.get("student")) for row in contacts if row.get("student") and row.get("next_follow_up")
	}
	follow_up_ids.update(
		str(task.get("student_id"))
		for task in tasks
		if task.get("student_id") and task.get("status") not in TERMINAL_TASK_STATES
	)
	follow_up = len(follow_up_ids.intersection(student_ids))
	return [
		_kpi("assigned", assigned, assigned, "primary"),
		_kpi("uncontacted", uncontacted, assigned, "warning"),
		_kpi("follow-up", follow_up, assigned, "info"),
		_kpi("transfer", len(transfer_ids), assigned, "success"),
	]


def _kpi(identifier: str, value: int, assigned: int, tone: str) -> dict[str, Any]:
	return {
		"id": identifier,
		"value": max(0, int(value)),
		"deltaValue": None,
		"deltaUnit": "count",
		"comparisonPeriod": None,
		"direction": None,
		"ratioOfAssigned": round(value / assigned, 4) if assigned else None,
		"tone": tone,
	}


def _build_tasks(
	tasks: list[dict[str, Any]], report_date: date, as_of: datetime, timezone: ZoneInfo, priority_limit: int
) -> dict[str, Any]:
	for task in tasks:
		due = _as_timezone(task.get("due"), timezone)
		task["due"] = due
		task["is_overdue"] = bool(due and due < as_of and task["status"] not in TERMINAL_TASK_STATES)
		task["is_today"] = bool(due and due.date() == report_date)
	completed_today = sum(
		1
		for task in tasks
		if task["status"] == "done"
		and _as_timezone(task.get("completed"), timezone)
		and _as_timezone(task.get("completed"), timezone).date() == report_date
	)
	today_tasks = [task for task in tasks if task["is_today"] and task["status"] != "canceled"]
	open_tasks = [task for task in tasks if task["status"] not in TERMINAL_TASK_STATES]
	upcoming_end = report_date + timedelta(days=7)
	upcoming = [
		task for task in open_tasks if task.get("due") and report_date < task["due"].date() <= upcoming_end
	]
	priority_tasks = sorted(
		(task for task in open_tasks if task.get("due")),
		key=lambda task: (
			0 if task["is_overdue"] else 1,
			task["due"],
			PRIORITY_ORDER.get(task["priority"], 99),
			task["id"],
		),
	)[:priority_limit]
	completed = min(completed_today, len(today_tasks))
	total_today = len(today_tasks)
	return {
		"priority": {
			"overdueCount": sum(1 for task in open_tasks if task["is_overdue"]),
			"items": [_serialize_task(task, timezone) for task in priority_tasks],
		},
		"summary": {
			"today": {
				"total": total_today,
				"pending": max(total_today - completed, 0),
				"completed": completed,
			},
			"overdue": {"count": sum(1 for task in open_tasks if task["is_overdue"])},
			"upcoming": {"count": len(upcoming), "horizonDays": 7},
			"completion": {
				"completed": completed,
				"total": total_today,
				"rate": round(completed / total_today * 100, 1) if total_today else None,
			},
		},
	}


def _serialize_task(task: dict[str, Any], timezone: ZoneInfo) -> dict[str, Any]:
	return {
		"id": task["id"],
		"studentId": task["student_id"],
		"studentName": task.get("student_name") or "Hồ sơ chưa đặt tên",
		"taskType": task["task_type"],
		"taskTypeLabel": task["task_type_label"],
		"dueAt": task["due"].isoformat(timespec="seconds") if task.get("due") else None,
		"detail": _redact_sensitive(task.get("detail") or task.get("title") or ""),
		"priority": task["priority"],
		"status": task["status"],
		"isOverdue": bool(task.get("is_overdue")),
	}


def _build_student_status(
	students: list[dict[str, Any]], contacts: list[dict[str, Any]], interactions: list[dict[str, Any]]
) -> dict[str, Any]:
	transfer_ids = _transfer_ids(students, contacts)
	attempted_ids = {str(row.get("student")) for row in interactions if row.get("student")}
	connected_ids = {
		str(row.get("student")) for row in interactions if row.get("student") and _is_connected(row)
	}
	counts = {"new": 0, "consulting": 0, "connected": 0, "transferred": 0}
	for row in students:
		student_id = str(row.get("name") or "")
		if student_id in transfer_ids:
			bucket = "transferred"
		elif student_id not in attempted_ids:
			bucket = "new"
		elif student_id in connected_ids:
			bucket = "connected"
		else:
			bucket = "consulting"
		counts[bucket] += 1
	total = len(students)
	labels = {
		"new": "Mới nhận",
		"consulting": "Đang tư vấn",
		"connected": "Đã kết nối",
		"transferred": "Đã chuyển Sale",
	}
	return {
		"total": total,
		"items": [
			{
				"id": identifier,
				"label": labels[identifier],
				"count": count,
				"share": round(count / total * 100, 1) if total else None,
			}
			for identifier, count in counts.items()
		],
	}


def _transfer_ids(students: list[dict[str, Any]], contacts: list[dict[str, Any]]) -> set[str]:
	ids = {
		str(row.get("name"))
		for row in students
		if str(row.get("lifecycle_stage") or "") in {"Applicant", "Enrolled"}
	}
	for row in contacts:
		readiness = str(row.get("readiness_level") or "")
		if readiness.startswith("Level 3") or readiness.startswith("Level 4"):
			if row.get("student"):
				ids.add(str(row["student"]))
	return ids


def _build_contact_trend(
	interactions: list[dict[str, Any]], report_date: date, default_range: str, timezone: ZoneInfo
) -> dict[str, Any]:
	return {
		"defaultRange": default_range,
		"ranges": {
			"7d": _trend_range(interactions, report_date, 7, "day", timezone),
			"30d": _trend_range(interactions, report_date, 30, "week", timezone),
		},
	}


def _trend_range(
	interactions: list[dict[str, Any]], report_date: date, days: int, bucket: str, timezone: ZoneInfo
) -> dict[str, Any]:
	from_date = report_date - timedelta(days=days - 1)
	points: list[dict[str, Any]] = []
	if bucket == "day":
		starts = [from_date + timedelta(days=index) for index in range(days)]
	else:
		starts = [from_date + timedelta(days=index) for index in range(0, days, 7)]
	for start in starts:
		end = min(start + timedelta(days=6 if bucket == "week" else 0), report_date)
		rows = [
			row
			for row in interactions
			if _interaction_date(row, timezone) and start <= _interaction_date(row, timezone) <= end
		]
		points.append(
			{
				"label": _day_label(start) if bucket == "day" else f"Tuần {len(points) + 1}",
				"periodStart": start.isoformat(),
				"periodEnd": end.isoformat(),
				"contacts": len(rows),
				"connected": sum(1 for row in rows if _is_connected(row)),
			}
		)
	return {
		"from": from_date.isoformat(),
		"to": report_date.isoformat(),
		"points": points,
		"totals": {
			"contacts": sum(point["contacts"] for point in points),
			"connected": sum(point["connected"] for point in points),
		},
	}


def _build_contact_outcomes(
	interactions: list[dict[str, Any]], report_date: date, selected_range: str, timezone: ZoneInfo
) -> dict[str, Any]:
	days = 7 if selected_range == "7d" else 30
	from_date = report_date - timedelta(days=days - 1)
	rows = [
		row
		for row in interactions
		if _interaction_date(row, timezone)
		and from_date <= _interaction_date(row, timezone) <= report_date
		and row.get("outcome")
	]
	counts: dict[str, dict[str, Any]] = {}
	for row in rows:
		identifier = _outcome_id(row.get("outcome"))
		label = _outcome_label(identifier, row.get("outcome"))
		if identifier not in counts:
			counts[identifier] = {"id": identifier, "label": label, "count": 0}
		counts[identifier]["count"] += 1
	total = len(rows)
	items = [
		{
			**item,
			"share": round(item["count"] / total * 100, 1) if total else None,
		}
		for item in counts.values()
	]
	return {
		"from": from_date.isoformat(),
		"to": report_date.isoformat(),
		"total": total,
		"connectedRate": round(
			sum(item["count"] for item in items if item["id"] == "connected") / total * 100, 1
		)
		if total
		else None,
		"items": items,
	}


def _interaction_date(row: dict[str, Any], timezone: ZoneInfo) -> date | None:
	value = _coerce_datetime(row.get("interaction_datetime"))
	localized = _as_timezone(value, timezone)
	return localized.date() if localized else None


def _is_connected(row: dict[str, Any]) -> bool:
	interaction_type = str(row.get("interaction_type") or "").strip().casefold()
	return interaction_type in {"connected", "counseling"} or _outcome_id(row.get("outcome")) == "connected"


def _outcome_id(value: Any) -> str:
	text = str(value or "").strip().casefold()
	if text in CONNECTED_OUTCOMES:
		return "connected"
	if text in {"no response", "uncontactable", "missed"}:
		return "missed"
	if text in {"follow up needed", "follow-up", "follow up"}:
		return "follow-up"
	if text in {"qualified", "interest increased"}:
		return "qualified"
	return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "other"


def _outcome_label(identifier: str, raw: Any) -> str:
	return {
		"connected": "Đã kết nối",
		"missed": "Không bắt máy",
		"follow-up": "Follow-up",
		"qualified": "Có nhu cầu",
	}.get(identifier, str(raw or "Khác"))


def _priority(value: Any) -> str:
	text = str(value or "medium").strip().lower()
	return text if text in PRIORITY_ORDER else "medium"


def _task_type(value: Any, detail: Any = None) -> str:
	text = f"{value or ''} {detail or ''}".casefold()
	if any(token in text for token in ("call", "phone", "gọi", "tel")):
		return "call"
	if any(token in text for token in ("follow", "chăm sóc", "gọi lại")):
		return "follow-up"
	if any(token in text for token in ("message", "nhắn", "zalo", "sms")):
		return "message"
	return "other"


def _task_type_label(value: Any, detail: Any = None) -> str:
	return {
		"call": "Gọi lại",
		"follow-up": "Follow-up",
		"message": "Nhắn tin",
		"other": "Việc khác",
	}[_task_type(value, detail)]


def _coerce_datetime(value: Any) -> datetime | None:
	if isinstance(value, datetime):
		return value
	if isinstance(value, date):
		return datetime.combine(value, time.min)
	if not value:
		return None
	try:
		return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
	except ValueError:
		try:
			return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S.%f")
		except ValueError:
			try:
				return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
			except ValueError:
				return None


def _as_timezone(value: datetime | None, timezone: ZoneInfo) -> datetime | None:
	if value is None:
		return None
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone)
	return value.astimezone(timezone)


def _day_label(value: date) -> str:
	return ("T2", "T3", "T4", "T5", "T6", "T7", "CN")[value.weekday()]


def _plain_text(value: Any) -> str:
	return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def _redact_sensitive(value: str) -> str:
	value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", value)
	return re.sub(r"(?<!\d)(?:\+?\d[\d .-]{7,}\d)(?!\d)", "[phone]", value)[:500]
