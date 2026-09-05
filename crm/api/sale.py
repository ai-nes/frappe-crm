"""Permission-scoped overview API for the Sale workspace.

The endpoint returns one server-side snapshot for the Sale dashboard.  Every
source query is scoped to the Sale user before aggregates are calculated, so
the browser cannot widen the dataset by sending an owner or assignment id.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date as Date
from datetime import datetime, timedelta
from datetime import timezone as DateTimezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe

from crm.api.director_school_common import parse_limit, raise_api_error
from crm.fcrm.role_policy import resolve_crm_profile

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
TREND_RANGES = {"4w", "12w"}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
TERMINAL_TASK_STATUSES = {"Done", "Canceled"}
TERMINAL_ACTION_STATES = {"completed", "cancelled", "rejected", "superseded"}

STAGE_ORDER = (
	"assigned",
	"contacted",
	"consulted",
	"interested",
	"documents",
	"confirmed",
	"admitted",
)
STAGE_LABELS = {
	"assigned": "Đang phụ trách",
	"contacted": "Đã liên hệ",
	"consulted": "Đã tư vấn",
	"interested": "Có nhu cầu",
	"documents": "Đang làm hồ sơ",
	"confirmed": "Đã xác nhận",
	"admitted": "Nhập học",
}
STUDENT_STATUS_ORDER = ("new", "consulting", "waiting", "documents", "admission")
STUDENT_STATUS_LABELS = {
	"new": "Mới phân công",
	"consulting": "Đang tư vấn",
	"waiting": "Chờ phản hồi",
	"documents": "Đang làm hồ sơ",
	"admission": "Chờ nhập học",
}
ATTENTION_ORDER = ("at-risk", "high-intent", "blocked")
OPERATION_ORDER = ("overdue-tasks", "missing-documents")

STUDENT_FIELDS = [
	"name",
	"student_name",
	"lifecycle_stage",
	"enrollment_status",
	"admission_year",
	"interest_level",
	"fit_level",
	"enrollment_date",
	"modified",
]
CONTACT_FIELDS = [
	"name",
	"student",
	"enrollment_status",
	"lifecycle_stage",
	"lead_status",
	"readiness_level",
	"quality_bucket",
	"is_verified_lead",
	"first_contact_time",
	"next_follow_up",
]
APPLICATION_FIELDS = [
	"name",
	"student",
	"status",
	"document_total",
	"document_completed",
	"submitted_at",
	"enrolled_at",
	"modified",
]
INTERACTION_FIELDS = [
	"name",
	"student",
	"interaction_type",
	"interaction_datetime",
	"outcome",
	"source_verified",
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
TASK_FIELDS = [
	"name",
	"title",
	"description",
	"student",
	"priority",
	"status",
	"start_date",
	"due_date",
	"modified",
	"creation",
]


@frappe.whitelist(methods=["GET"])
def get_sale_overview(
	admissionYear: str | int | None = None,
	date: str | None = None,
	trendRange: str = "4w",
	timezone: str = DEFAULT_TIMEZONE,
	priorityLimit: str | int = 4,
) -> dict[str, Any]:
	"""Return one consistent, permission-scoped Sale dashboard snapshot."""
	access = _require_access()
	report_timezone = _parse_timezone(timezone)
	report_date = _parse_report_date(date, report_timezone)
	admission_year = _resolve_admission_year(admissionYear)
	trend_range = _parse_range(trendRange)
	priority_limit = parse_limit(priorityLimit, field="priorityLimit", minimum=1, maximum=10, default=4)
	as_of = _now(report_timezone)
	warnings: list[str] = []
	staff = _resolve_sale_staff(access["user"])
	if not staff:
		warnings.append("scope.sale_staff_not_found")

	students = _load_students(staff, admission_year, warnings)
	student_ids = [str(row.get("name")) for row in students if row.get("name")]
	student_names = {
		str(row.get("name")): str(row.get("student_name") or "Hồ sơ chưa đặt tên")
		for row in students
		if row.get("name")
	}
	contacts = _load_contacts(student_ids, warnings)
	applications = _load_applications(student_ids, admission_year, warnings)
	interactions = _load_interactions(student_ids, warnings)
	tasks = _load_tasks(student_ids, warnings)
	for task in tasks:
		task["student_name"] = student_names.get(task.get("student_id"), "Hồ sơ chưa đặt tên")

	records = _build_student_records(students, contacts, applications, interactions)
	task_snapshot = _build_tasks(tasks, report_date, as_of, report_timezone, priority_limit)
	missing_document_ids = _missing_document_ids(applications)
	status = "available"
	if warnings:
		status = "unavailable" if _has_warning(warnings, "students") else "partial"

	return {
		"meta": {
			"viewer": _viewer(access["user"]),
			"admissionYear": _year_number(admission_year),
			"date": report_date.isoformat(),
			"asOf": as_of.isoformat(timespec="seconds"),
			"timezone": getattr(report_timezone, "key", str(report_timezone)),
			"status": status,
			"warnings": warnings,
		},
		"kpis": _build_kpis(records),
		"tasks": task_snapshot,
		"pipeline": _build_pipeline(records),
		"attention": _build_attention(
			records, interactions, missing_document_ids, tasks, as_of, report_timezone
		),
		"conversionTrend": _build_conversion_trend(records, report_date, trend_range, report_timezone),
		"studentStatus": _build_student_status(records),
		"operations": _build_operations(task_snapshot, missing_document_ids),
	}


def _require_access() -> dict[str, Any]:
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		raise_api_error(
			"UNAUTHENTICATED",
			"Bạn cần đăng nhập để truy cập dữ liệu Sale.",
			frappe.AuthenticationError,
			401,
		)
	if user != "Administrator" and frappe.db.get_value("User", user, "enabled") not in (1, True, "1"):
		raise_api_error("UNAUTHENTICATED", "Tài khoản không hoạt động.", frappe.AuthenticationError, 401)
	if user == "Administrator" or "System Manager" in set(frappe.get_roles(user)):
		return {"user": user, "profile": "platform_superuser"}
	profile = resolve_crm_profile(set(frappe.get_roles(user)))
	if profile != "sales":
		raise_api_error(
			"FORBIDDEN",
			"Bạn không có quyền truy cập tổng quan Sale.",
			frappe.PermissionError,
			403,
		)
	return {"user": user, "profile": profile}


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


def _parse_report_date(value: Any, timezone: ZoneInfo) -> Date:
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


def _resolve_admission_year(value: Any) -> str:
	if value not in (None, ""):
		text = str(value).strip()
		if not re.fullmatch(r"\d{4}", text) or not 2000 <= int(text) <= 2100:
			raise_api_error(
				"INVALID_QUERY", "Tham số admissionYear không hợp lệ.", frappe.ValidationError, 400
			)
		rows = _get_list(
			"CRM Admission Year",
			filters={"name": text},
			fields=["name", "year_name"],
			limit_page_length=1,
			warnings=None,
		)
		if not rows:
			rows = _get_list(
				"CRM Admission Year",
				filters={"year_name": text},
				fields=["name", "year_name"],
				limit_page_length=1,
				warnings=None,
			)
		if rows:
			return str(rows[0].get("name") or rows[0].get("year_name") or text)
		raise_api_error(
			"ADMISSION_YEAR_NOT_FOUND", "Không tìm thấy kỳ tuyển sinh.", frappe.DoesNotExistError, 404
		)

	rows = _get_list(
		"CRM Admission Year",
		filters={"is_active": 1},
		fields=["name", "year_name"],
		limit_page_length=20,
		warnings=None,
		order_by="year_name desc, name desc",
	)
	if rows:
		return str(rows[0].get("name") or rows[0].get("year_name"))
	current_year = str(_now(ZoneInfo(DEFAULT_TIMEZONE)).year)
	rows = _get_list(
		"CRM Admission Year",
		filters={"name": current_year},
		fields=["name", "year_name"],
		limit_page_length=1,
		warnings=None,
	)
	if rows:
		return str(rows[0].get("name") or rows[0].get("year_name") or current_year)
	raise_api_error(
		"ADMISSION_YEAR_NOT_FOUND", "Không tìm thấy kỳ tuyển sinh hiện hành.", frappe.DoesNotExistError, 404
	)


def _parse_range(value: Any) -> str:
	text = str(value or "4w").strip().lower()
	if text not in TREND_RANGES:
		raise_api_error(
			"INVALID_QUERY", "Tham số trendRange phải là 4w hoặc 12w.", frappe.ValidationError, 400
		)
	return text


def _resolve_sale_staff(user: str) -> dict[str, Any] | None:
	rows = _get_list(
		"CRM Staff",
		filters={"user": user, "is_active": 1},
		fields=["name", "user", "full_name"],
		limit_page_length=1,
		warnings=None,
	)
	return dict(rows[0]) if rows else None


def _viewer(user: str) -> dict[str, str]:
	display_name = frappe.db.get_value("User", user, "full_name") or user
	return {"id": str(user), "displayName": str(display_name)}


def _load_students(
	staff: dict[str, Any] | None, admission_year: str, warnings: list[str]
) -> list[dict[str, Any]]:
	if not staff or not staff.get("name"):
		return []
	return [
		dict(row)
		for row in _get_list(
			"CRM Student",
			filters={
				"owner_staff": staff["name"],
				"admission_year": admission_year,
				"lifecycle_stage": ["!=", "Lost"],
			},
			fields=STUDENT_FIELDS,
			order_by="name asc",
			limit_page_length=0,
			warnings=warnings,
			warning_key="students",
		)
	]


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


def _load_applications(
	student_ids: list[str], admission_year: str, warnings: list[str]
) -> list[dict[str, Any]]:
	if not student_ids:
		return []
	return [
		dict(row)
		for row in _get_list(
			"CRM Admission Application",
			filters={"student": ["in", student_ids], "admission_year": admission_year},
			fields=APPLICATION_FIELDS,
			order_by="modified desc, name desc",
			limit_page_length=0,
			warnings=warnings,
			warning_key="applications",
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
	try:
		if not frappe.db.table_exists(doctype):
			if warnings is not None and warning_key:
				warnings.append(f"{warning_key}.source_unavailable")
			return []
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


def _build_student_records(
	students: list[dict[str, Any]],
	contacts: list[dict[str, Any]],
	applications: list[dict[str, Any]],
	interactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
	contacts_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	applications_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	interactions_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in contacts:
		if row.get("student"):
			contacts_by_student[str(row["student"])].append(row)
	for row in applications:
		if row.get("student"):
			applications_by_student[str(row["student"])].append(row)
	for row in interactions:
		if row.get("student"):
			interactions_by_student[str(row["student"])].append(row)

	records = []
	for student in students:
		student_id = str(student.get("name") or "")
		if not student_id:
			continue
		student_contacts = contacts_by_student.get(student_id, [])
		student_applications = applications_by_student.get(student_id, [])
		student_interactions = interactions_by_student.get(student_id, [])
		stages = {"assigned"}
		if _has_contact_attempt(student_contacts, student_interactions):
			stages.add("contacted")
		if _is_consulted(student, student_contacts, student_applications, student_interactions):
			stages.add("consulted")
		if _is_interested(student, student_contacts, student_interactions):
			stages.add("interested")
		if _has_documents_stage(student, student_applications):
			stages.add("documents")
		if _is_confirmed(student, student_applications):
			stages.add("confirmed")
		if _is_admitted(student, student_applications):
			stages.add("confirmed")
			stages.add("admitted")

		consulted_at = _first_datetime(
			row.get("interaction_datetime") for row in student_interactions if _is_consulted_interaction(row)
		)
		admitted_at = _first_datetime(
			[row.get("enrolled_at") for row in student_applications] + [student.get("enrollment_date")]
		)
		records.append(
			{
				"id": student_id,
				"name": str(student.get("student_name") or "Hồ sơ chưa đặt tên"),
				"stages": stages,
				"status": _student_status(stages),
				"consulted_at": consulted_at,
				"admitted_at": admitted_at,
				"last_interaction": _latest_interaction(student_interactions),
				"missing_documents": _student_has_missing_documents(student_applications),
				"qualification": "interested" in stages,
			}
		)
	return records


def _build_kpis(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
	return [
		{"id": "assigned", "value": len(records)},
		{"id": "consulting", "value": _count_status(records, "consulting")},
		{"id": "qualified", "value": sum(bool(row.get("qualification")) for row in records)},
		{"id": "documents", "value": _count_status(records, "documents")},
		{"id": "admission", "value": _count_status(records, "admission")},
	]


def _build_pipeline(records: list[dict[str, Any]]) -> dict[str, Any]:
	previous = len(records)
	stages = []
	for stage_id in STAGE_ORDER:
		value = min(previous, sum(stage_id in row["stages"] for row in records))
		previous = value
		stages.append({"id": stage_id, "label": STAGE_LABELS[stage_id], "count": max(0, value)})
	return {"stages": stages}


def _build_attention(
	records: list[dict[str, Any]],
	interactions: list[dict[str, Any]],
	missing_document_ids: set[str],
	tasks: list[dict[str, Any]],
	as_of: datetime,
	timezone: ZoneInfo,
) -> dict[str, Any]:
	interactions_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in interactions:
		if row.get("student"):
			interactions_by_student[str(row["student"])].append(row)
	atrisk = 0
	high_intent = 0
	blocked_ids = set(missing_document_ids)
	for record in records:
		student_interactions = interactions_by_student.get(record["id"], [])
		latest = _latest_interaction(student_interactions)
		if latest and _outcome_id(latest.get("outcome")) == "missed":
			atrisk += 1
		if record.get("qualification") and not (set(record["stages"]) & {"confirmed", "admitted"}):
			high_intent += 1
		if _has_open_task_without_due(tasks, record["id"], as_of, timezone):
			blocked_ids.add(record["id"])
	return {
		"items": [
			{"id": "at-risk", "count": max(0, atrisk)},
			{"id": "high-intent", "count": max(0, high_intent)},
			{"id": "blocked", "count": sum(record["id"] in blocked_ids for record in records)},
		]
	}


def _build_conversion_trend(
	records: list[dict[str, Any]], report_date: Date, default_range: str, timezone: ZoneInfo
) -> dict[str, Any]:
	return {
		"defaultRange": default_range,
		"ranges": {
			"4w": _trend_range(records, report_date, 4, timezone),
			"12w": _trend_range(records, report_date, 12, timezone),
		},
	}


def _trend_range(
	records: list[dict[str, Any]], report_date: Date, weeks: int, timezone: ZoneInfo
) -> dict[str, Any]:
	current_week_start = report_date - timedelta(days=report_date.weekday())
	from_date = current_week_start - timedelta(days=(weeks - 1) * 7)
	points = []
	for index in range(weeks):
		start = from_date + timedelta(days=index * 7)
		end = min(start + timedelta(days=6), report_date)
		consulted = sum(_date_inclusive(row.get("consulted_at"), start, end, timezone) for row in records)
		admitted = sum(_date_inclusive(row.get("admitted_at"), start, end, timezone) for row in records)
		points.append(
			{
				"label": f"Tuần {index + 1}" if weeks == 4 else f"T{index + 1}",
				"periodStart": start.isoformat(),
				"periodEnd": end.isoformat(),
				"consulted": consulted,
				"admitted": admitted,
			}
		)
	return {
		"from": from_date.isoformat(),
		"to": report_date.isoformat(),
		"points": points,
	}


def _build_student_status(records: list[dict[str, Any]]) -> dict[str, Any]:
	counts = {status: 0 for status in STUDENT_STATUS_ORDER}
	for record in records:
		counts[record["status"]] += 1
	total = len(records)
	return {
		"total": total,
		"items": [
			{
				"id": status,
				"label": STUDENT_STATUS_LABELS[status],
				"count": counts[status],
				"share": round(counts[status] / total * 100, 1) if total else None,
			}
			for status in STUDENT_STATUS_ORDER
		],
	}


def _build_tasks(
	tasks: list[dict[str, Any]],
	report_date: Date,
	as_of: datetime,
	timezone: ZoneInfo,
	priority_limit: int,
) -> dict[str, Any]:
	for task in tasks:
		due = _as_timezone(task.get("due_at"), timezone)
		task["due_at"] = due
		task["is_overdue"] = bool(due and due < as_of and not _task_is_terminal(task))
		task["is_today"] = bool(due and due.date() == report_date)
	open_tasks = [task for task in tasks if not _task_is_terminal(task)]
	today_tasks = [task for task in tasks if task["is_today"] and not _task_is_canceled(task)]
	completed_today = sum(1 for task in today_tasks if _task_is_done(task))
	upcoming_end = report_date + timedelta(days=7)
	upcoming = [
		task
		for task in open_tasks
		if task.get("due_at") and report_date < task["due_at"].date() <= upcoming_end
	]
	priority_tasks = sorted(
		(task for task in open_tasks),
		key=lambda task: (
			0 if task["is_overdue"] else 1,
			0 if task.get("due_at") else 1,
			task.get("due_at") or datetime.max.replace(tzinfo=as_of.tzinfo),
			PRIORITY_ORDER.get(task.get("priority", "medium"), 1),
			task["id"],
		),
	)[:priority_limit]
	total_today = len(today_tasks)
	completed_today = min(completed_today, total_today)
	return {
		"priority": {
			"overdueCount": sum(task["is_overdue"] for task in open_tasks),
			"items": [_serialize_task(task) for task in priority_tasks],
		},
		"summary": {
			"today": {
				"total": total_today,
				"pending": max(total_today - completed_today, 0),
				"completed": completed_today,
			},
			"overdue": {"count": sum(task["is_overdue"] for task in open_tasks)},
			"upcoming": {"count": len(upcoming), "horizonDays": 7},
		},
	}


def _build_operations(task_snapshot: dict[str, Any], missing_document_ids: set[str]) -> dict[str, Any]:
	overdue = int(task_snapshot["summary"]["overdue"]["count"])
	missing = len(missing_document_ids)
	return {
		"total": overdue + missing,
		"items": [
			{"id": "overdue-tasks", "count": overdue},
			{"id": "missing-documents", "count": missing},
		],
	}


def _normalize_action_task(row: dict[str, Any]) -> dict[str, Any]:
	state = str(row.get("state") or "pending").strip().lower()
	status = (
		"Done"
		if state == "completed"
		else "Canceled"
		if state in TERMINAL_ACTION_STATES
		else "In Progress"
		if state == "in-progress"
		else "Todo"
	)
	action_type = f"{row.get('action_type') or ''} {row.get('action') or ''}"
	return {
		"id": f"CRM Action Item:{row.get('name')}",
		"student_id": str(row.get("student") or ""),
		"title": str(row.get("objective") or "Việc cần xử lý"),
		"detail": str(row.get("objective") or ""),
		"task_type": _task_type(action_type, row.get("objective")),
		"priority": _priority(row.get("priority")),
		"status": status,
		"start_at": None,
		"due_at": _coerce_datetime(row.get("due_at")),
		"completed_at": _coerce_datetime(row.get("completed_at")),
	}


def _normalize_generic_task(row: dict[str, Any]) -> dict[str, Any]:
	title = str(row.get("title") or "Việc cần xử lý")
	detail = _plain_text(row.get("description")) or title
	status = str(row.get("status") or "Todo").strip().casefold()
	return {
		"id": f"Task:{row.get('name')}",
		"student_id": str(row.get("student") or ""),
		"title": title,
		"detail": detail,
		"task_type": _task_type(title, detail),
		"priority": _generic_priority(row.get("priority")),
		"status": "Done"
		if status == "done"
		else "Canceled"
		if status == "canceled"
		else "In Progress"
		if status == "in progress"
		else "Todo",
		"start_at": _coerce_datetime(row.get("start_date")),
		"due_at": _coerce_datetime(row.get("due_date")),
		"completed_at": _coerce_datetime(row.get("modified")) if status == "done" else None,
	}


def _serialize_task(task: dict[str, Any]) -> dict[str, Any]:
	return {
		"id": task["id"],
		"studentId": task["student_id"],
		"studentName": task.get("student_name") or "Hồ sơ chưa đặt tên",
		"title": _redact_sensitive(task.get("title") or ""),
		"type": task["task_type"],
		"startAt": task["start_at"].isoformat(timespec="seconds") if task.get("start_at") else None,
		"dueAt": task["due_at"].isoformat(timespec="seconds") if task.get("due_at") else None,
		"context": _redact_sensitive(task.get("detail") or "") or None,
		"priority": task["priority"].title(),
		"status": task["status"],
		"isOverdue": bool(task.get("is_overdue")),
	}


def _task_type(value: Any, detail: Any = None) -> str:
	text = _fold(f"{value or ''} {detail or ''}")
	if any(token in text for token in ("document", "ho ba", "giay to", "hoc ba", "ho so")):
		return "document"
	if any(token in text for token in ("call", "phone", "goi", "tel")):
		return "call"
	if any(token in text for token in ("message", "nhan", "zalo", "sms")):
		return "message"
	return "other"


def _priority(value: Any) -> str:
	text = str(value or "medium").strip().lower()
	return text if text in PRIORITY_ORDER else "medium"


def _generic_priority(value: Any) -> str:
	text = str(value or "Medium").strip().lower()
	return text if text in PRIORITY_ORDER else "medium"


def _task_is_terminal(task: dict[str, Any]) -> bool:
	return task.get("status") in TERMINAL_TASK_STATUSES


def _task_is_canceled(task: dict[str, Any]) -> bool:
	return task.get("status") == "Canceled"


def _task_is_done(task: dict[str, Any]) -> bool:
	return task.get("status") == "Done"


def _has_open_task_without_due(
	tasks: list[dict[str, Any]], student_id: str, as_of: datetime, timezone: ZoneInfo
) -> bool:
	return any(
		task.get("student_id") == student_id
		and not _task_is_terminal(task)
		and task.get("due_at") is None
		and task.get("status") != "Done"
		for task in tasks
	)


def _has_contact_attempt(contacts: list[dict[str, Any]], interactions: list[dict[str, Any]]) -> bool:
	return bool(interactions) or any(row.get("first_contact_time") for row in contacts)


def _is_consulted(
	student: dict[str, Any],
	contacts: list[dict[str, Any]],
	applications: list[dict[str, Any]],
	interactions: list[dict[str, Any]],
) -> bool:
	if any(_is_consulted_interaction(row) for row in interactions):
		return True
	if any(_fold(row.get("enrollment_status")) in {"dang tu van", "da tu van"} for row in contacts):
		return True
	return str(student.get("lifecycle_stage") or "") in {"Applicant", "Enrolled"} or any(
		_fold(row.get("status")) in {"submitted", "under review", "accepted", "enrolled"}
		for row in applications
	)


def _is_interested(
	student: dict[str, Any], contacts: list[dict[str, Any]], interactions: list[dict[str, Any]]
) -> bool:
	if _fold(student.get("lifecycle_stage")) == "mql":
		return True
	if _fold(student.get("interest_level")) in {"high", "medium"}:
		return True
	if _fold(student.get("fit_level")) == "high":
		return True
	for row in contacts:
		text = " ".join(
			_fold(row.get(field))
			for field in ("readiness_level", "quality_bucket", "lead_status", "enrollment_status")
		)
		if any(
			token in text
			for token in ("qualified", "high intent", "hot", "level 2", "level 3", "level 4", "co trien vong")
		):
			return True
	return any(_outcome_id(row.get("outcome")) == "qualified" for row in interactions)


def _has_documents_stage(student: dict[str, Any], applications: list[dict[str, Any]]) -> bool:
	if str(student.get("lifecycle_stage") or "") == "Applicant":
		return True
	return any(
		_fold(row.get("status")) in {"submitted", "under review"} or _student_has_missing_documents([row])
		for row in applications
	)


def _is_confirmed(student: dict[str, Any], applications: list[dict[str, Any]]) -> bool:
	if _fold(student.get("enrollment_status")) in {"da xac nhan", "da trung tuyen"}:
		return True
	return any(_fold(row.get("status")) == "accepted" for row in applications)


def _is_admitted(student: dict[str, Any], applications: list[dict[str, Any]]) -> bool:
	if (
		str(student.get("lifecycle_stage") or "") == "Enrolled"
		or _fold(student.get("enrollment_status")) == "da nhap hoc"
	):
		return True
	return any(_fold(row.get("status")) == "enrolled" for row in applications)


def _student_status(stages: set[str]) -> str:
	if stages & {"confirmed", "admitted"}:
		return "admission"
	if "documents" in stages:
		return "documents"
	if stages & {"consulted", "interested"}:
		return "consulting"
	if "contacted" in stages:
		return "waiting"
	return "new"


def _student_has_missing_documents(applications: list[dict[str, Any]]) -> bool:
	return any(
		int(row.get("document_total") or 0) > int(row.get("document_completed") or 0) for row in applications
	)


def _missing_document_ids(applications: list[dict[str, Any]]) -> set[str]:
	return {
		str(row.get("student"))
		for row in applications
		if row.get("student") and _student_has_missing_documents([row])
	}


def _count_status(records: list[dict[str, Any]], status: str) -> int:
	return sum(row.get("status") == status for row in records)


def _is_consulted_interaction(row: dict[str, Any]) -> bool:
	interaction_type = _fold(row.get("interaction_type"))
	return any(token in interaction_type for token in ("counsel", "tu van", "consult")) or _outcome_id(
		row.get("outcome")
	) in {
		"qualified",
	}


def _latest_interaction(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
	return max(rows, key=lambda row: _datetime_sort_key(row.get("interaction_datetime")), default=None)


def _outcome_id(value: Any) -> str:
	text = _fold(value)
	if text in {"captured", "resolved", "converted", "connected", "counseling", "tu van"}:
		return "connected"
	if text in {"no response", "no-response", "uncontactable", "missed", "khong phan hoi"}:
		return "missed"
	if text in {"follow up needed", "follow-up", "follow up", "can goi lai"}:
		return "follow-up"
	if text in {"qualified", "interest increased", "co trien vong", "co nhu cau"}:
		return "qualified"
	return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "other"


def _first_datetime(values: Any) -> datetime | None:
	parsed = [_coerce_datetime(value) for value in values]
	valid = [value for value in parsed if value]
	return min(valid, key=_datetime_sort_key, default=None)


def _datetime_sort_key(value: Any) -> float:
	parsed = _coerce_datetime(value)
	if not parsed:
		return float("-inf")
	if parsed.tzinfo is None:
		parsed = parsed.replace(tzinfo=DateTimezone.utc)
	return parsed.timestamp()


def _coerce_datetime(value: Any) -> datetime | None:
	if not value:
		return None
	if isinstance(value, datetime):
		return value
	try:
		return frappe.utils.get_datetime(value)
	except (AttributeError, TypeError, ValueError):
		try:
			return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
		except ValueError:
			return None


def _as_timezone(value: datetime | None, timezone: ZoneInfo) -> datetime | None:
	if value is None:
		return None
	if value.tzinfo is None:
		return value.replace(tzinfo=timezone)
	return value.astimezone(timezone)


def _date_inclusive(value: Any, start: Date, end: Date, timezone: ZoneInfo) -> bool:
	parsed = _as_timezone(_coerce_datetime(value), timezone)
	return bool(parsed and start <= parsed.date() <= end)


def _now(timezone: ZoneInfo) -> datetime:
	now = frappe.utils.now_datetime()
	return _as_timezone(_coerce_datetime(now), timezone) or datetime.now(timezone)


def _year_number(value: Any) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return 0


def _has_warning(warnings: list[str], key: str) -> bool:
	return any(item.startswith(f"{key}.") for item in warnings)


def _plain_text(value: Any) -> str:
	return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def _redact_sensitive(value: str) -> str:
	value = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", value)
	return re.sub(r"(?<!\d)(?:\+?\d[\d .-]{7,}\d)(?!\d)", "[phone]", value)[:500]


def _fold(value: Any) -> str:
	text = unicodedata.normalize("NFKD", str(value or "").casefold())
	return "".join(char for char in text if not unicodedata.combining(char)).replace("đ", "d")
