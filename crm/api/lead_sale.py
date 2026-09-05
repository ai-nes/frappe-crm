"""Permission-scoped overview API for the Lead Sales dashboard.

The endpoint builds one snapshot from the current Lead Sales permission scope.
The browser may choose presentation options (date, timezone, trend range and
member limit), but it cannot choose a team, owner or student scope.
"""

from __future__ import annotations

import calendar
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import frappe

from crm.api import sale as sale_overview
from crm.api.director_school_common import parse_limit, raise_api_error
from crm.fcrm.role_policy import resolve_crm_profile

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
TREND_RANGES = {"4w", "3m"}
STUDENT_STATUS_ORDER = ("consulting", "waiting", "documents", "admission", "new")
STUDENT_STATUS_LABELS = {
	"consulting": "Đang tư vấn",
	"waiting": "Chờ phản hồi",
	"documents": "Đang làm hồ sơ",
	"admission": "Chờ nhập học",
	"new": "Mới nhận",
}
INTERVENTION_ORDER = ("unassigned", "not-contacted", "at-risk", "blocked")
TERMINAL_TASK_STATUSES = {"Done", "Canceled"}

STUDENT_FIELDS = [
	"name",
	"student_name",
	"lifecycle_stage",
	"enrollment_status",
	"admission_year",
	"owner_staff",
	"assigned_to",
	"creation",
	"enrollment_date",
	"interest_level",
	"fit_level",
]


@frappe.whitelist(methods=["GET"])
def get_lead_sale_overview(
	admissionYear: str | int | None = None,
	date: str | None = None,
	trendRange: str = "4w",
	timezone: str = DEFAULT_TIMEZONE,
	teamMemberLimit: str | int = 20,
) -> dict[str, Any]:
	"""Return one consistent, permission-scoped Lead Sales snapshot."""
	access = _require_access()
	report_timezone = _parse_timezone(timezone)
	report_date = _parse_report_date(date, report_timezone)
	admission_year = _resolve_admission_year(admissionYear)
	trend_range = _parse_range(trendRange)
	member_limit = parse_limit(teamMemberLimit, field="teamMemberLimit", minimum=1, maximum=50, default=20)
	as_of = _now(report_timezone)
	warnings: list[str] = []

	teams = _resolve_teams(access["user"], warnings)
	students = _load_students(admission_year, warnings)
	student_ids = [str(row.get("name")) for row in students if row.get("name")]
	contacts = sale_overview._load_contacts(student_ids, warnings)
	applications = sale_overview._load_applications(student_ids, admission_year, warnings)
	interactions = sale_overview._load_interactions(student_ids, warnings)
	tasks = sale_overview._load_tasks(student_ids, warnings)

	records = _build_records(students, contacts, applications, interactions)
	active_records = [row for row in records if _is_assigned(row)]
	missing_document_ids = sale_overview._missing_document_ids(applications)
	annotated_tasks = _annotate_tasks(tasks, as_of, report_timezone)

	status = "available"
	if warnings:
		status = "unavailable" if _has_warning(warnings, "students") else "partial"

	return {
		"meta": {
			"viewer": _viewer(access["user"]),
			"team": _team_meta(teams),
			"admissionYear": _year_number(admission_year),
			"date": report_date.isoformat(),
			"asOf": as_of.isoformat(timespec="seconds"),
			"timezone": getattr(report_timezone, "key", str(report_timezone)),
			"status": status,
			"warnings": sorted(set(warnings)),
		},
		"kpis": _build_kpis(records, active_records, missing_document_ids, annotated_tasks, report_date),
		"interventions": _build_interventions(
			records,
			contacts,
			interactions,
			missing_document_ids,
			annotated_tasks,
			as_of,
			report_timezone,
		),
		"teamPerformance": {
			"items": _build_team_performance(teams, records, member_limit),
		},
		"studentStatus": _build_student_status(active_records),
		"resultTrend": _build_result_trend(records, report_date, trend_range, report_timezone),
	}


def _require_access() -> dict[str, str]:
	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		raise_api_error(
			"UNAUTHENTICATED",
			"Bạn cần đăng nhập để truy cập tổng quan Lead Sales.",
			frappe.AuthenticationError,
			401,
		)
	if user != "Administrator" and frappe.db.get_value("User", user, "enabled") not in (1, True, "1"):
		raise_api_error("UNAUTHENTICATED", "Tài khoản không hoạt động.", frappe.AuthenticationError, 401)
	profile = resolve_crm_profile(set(frappe.get_roles(user)))
	if profile != "lead_sales":
		raise_api_error(
			"FORBIDDEN",
			"Bạn không có quyền truy cập tổng quan Lead Sales.",
			frappe.PermissionError,
			403,
		)
	return {"user": str(user), "profile": profile}


def _parse_timezone(value: Any) -> ZoneInfo:
	text = str(value or DEFAULT_TIMEZONE).strip()
	if not text or len(text) > 64:
		raise_api_error("INVALID_QUERY", "Tham số timezone phải là IANA timezone hợp lệ.", frappe.ValidationError, 400)
	try:
		return ZoneInfo(text)
	except ZoneInfoNotFoundError:
		raise_api_error("INVALID_QUERY", "Tham số timezone phải là IANA timezone hợp lệ.", frappe.ValidationError, 400)
	raise AssertionError("raise_api_error always raises")


def _parse_report_date(value: Any, timezone: ZoneInfo) -> date:
	if value in (None, ""):
		return _now(timezone).date()
	text = str(value).strip()
	try:
		parsed = datetime.strptime(text, "%Y-%m-%d").date()
	except (TypeError, ValueError):
		raise_api_error("INVALID_QUERY", "Tham số date phải có định dạng YYYY-MM-DD.", frappe.ValidationError, 400)
	if parsed.isoformat() != text:
		raise_api_error("INVALID_QUERY", "Tham số date phải có định dạng YYYY-MM-DD.", frappe.ValidationError, 400)
	return parsed


def _parse_range(value: Any) -> str:
	text = str(value or "4w").strip().lower()
	if text not in TREND_RANGES:
		raise_api_error("INVALID_QUERY", "Tham số trendRange phải là 4w hoặc 3m.", frappe.ValidationError, 400)
	return text


def _resolve_admission_year(value: Any) -> str:
	if value not in (None, ""):
		text = str(value).strip()
		if not re.fullmatch(r"\d{4}", text) or not 2000 <= int(text) <= 2100:
			raise_api_error("INVALID_QUERY", "Tham số admissionYear không hợp lệ.", frappe.ValidationError, 400)
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
		raise_api_error("ADMISSION_YEAR_NOT_FOUND", "Không tìm thấy kỳ tuyển sinh.", frappe.DoesNotExistError, 404)

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
		"ADMISSION_YEAR_NOT_FOUND",
		"Không tìm thấy kỳ tuyển sinh hiện hành.",
		frappe.DoesNotExistError,
		404,
	)


def _resolve_teams(user: str, warnings: list[str]) -> list[dict[str, Any]]:
	staff_rows = _get_list(
		"CRM Staff",
		filters={"user": user, "is_active": 1},
		fields=["name", "full_name", "user"],
		limit_page_length=1,
		warnings=warnings,
		warning_key="team",
	)
	if not staff_rows:
		warnings.append("team.staff_not_found")
		return []
	staff_name = staff_rows[0].get("name")
	memberships = _get_list(
		"CRM Team Membership",
		filters={"parent": staff_name, "parenttype": "CRM Staff"},
		fields=["team", "function", "is_primary"],
		limit_page_length=0,
		warnings=warnings,
		warning_key="team",
	)
	team_ids = [str(row.get("team")) for row in memberships if row.get("team")]
	if not team_ids:
		warnings.append("team.membership_not_found")
		return []
	teams = _get_list(
		"CRM Team",
		filters={"name": ["in", team_ids], "team_type": "Sales", "is_active": 1},
		fields=["name", "team_name", "campus", "is_active"],
		limit_page_length=0,
		warnings=warnings,
		warning_key="team",
	)
	primary = {str(row.get("team")) for row in memberships if row.get("is_primary")}
	return sorted(teams, key=lambda row: (0 if str(row.get("name")) in primary else 1, str(row.get("name") or "")))


def _load_students(admission_year: str, warnings: list[str]) -> list[dict[str, Any]]:
	return [
		dict(row)
		for row in _get_list(
			"CRM Student",
			filters={"admission_year": admission_year, "lifecycle_stage": ["!=", "Lost"]},
			fields=STUDENT_FIELDS,
			limit_page_length=0,
			warnings=warnings,
			warning_key="students",
			order_by="name asc",
		)
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


def _build_records(
	students: list[dict[str, Any]],
	contacts: list[dict[str, Any]],
	applications: list[dict[str, Any]],
	interactions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
	records = sale_overview._build_student_records(students, contacts, applications, interactions)
	by_id = {str(row.get("name")): row for row in students if row.get("name")}
	for record in records:
		student = by_id.get(record["id"], {})
		record["owner_staff"] = student.get("owner_staff") or student.get("assigned_to")
		record["creation"] = student.get("creation")
	return records


def _build_kpis(
	records: list[dict[str, Any]],
	active_records: list[dict[str, Any]],
	missing_document_ids: set[str],
	tasks: list[dict[str, Any]],
	report_date: date,
) -> list[dict[str, int]]:
	open_tasks = [task for task in tasks if not _task_is_terminal(task)]
	needs_action_ids = {str(task.get("student_id")) for task in open_tasks if task.get("student_id")}
	new_count = sum(_date_of(row.get("creation")) == report_date for row in records)
	return [
		{"id": "active", "value": len(active_records)},
		{"id": "new", "value": new_count},
		{"id": "unassigned", "value": sum(not _is_assigned(row) for row in records)},
		{"id": "needs-action", "value": len(needs_action_ids)},
		{"id": "overdue", "value": sum(bool(task.get("is_overdue")) for task in open_tasks)},
		{"id": "documents", "value": len(missing_document_ids)},
	]


def _build_interventions(
	records: list[dict[str, Any]],
	contacts: list[dict[str, Any]],
	interactions: list[dict[str, Any]],
	missing_document_ids: set[str],
	tasks: list[dict[str, Any]],
	as_of: datetime,
	timezone: ZoneInfo,
) -> dict[str, list[dict[str, int]]]:
	contacts_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	interactions_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in contacts:
		if row.get("student"):
			contacts_by_student[str(row["student"])].append(row)
	for row in interactions:
		if row.get("student"):
			interactions_by_student[str(row["student"])].append(row)

	not_contacted = 0
	at_risk = 0
	blocked_ids = set(missing_document_ids)
	for record in records:
		student_id = record["id"]
		created_at = sale_overview._as_timezone(sale_overview._coerce_datetime(record.get("creation")), timezone)
		if (
			created_at
			and as_of - created_at > timedelta(hours=24)
			and not sale_overview._has_contact_attempt(
				contacts_by_student.get(student_id, []), interactions_by_student.get(student_id, [])
			)
		):
			not_contacted += 1
		latest = sale_overview._latest_interaction(interactions_by_student.get(student_id, []))
		if latest and sale_overview._outcome_id(latest.get("outcome")) == "missed":
			at_risk += 1
		if any(
			task.get("student_id") == student_id
			and not _task_is_terminal(task)
			and task.get("due_at") is None
			for task in tasks
		):
			blocked_ids.add(student_id)

	counts = {
		"unassigned": sum(not _is_assigned(row) for row in records),
		"not-contacted": not_contacted,
		"at-risk": at_risk,
		"blocked": sum(record["id"] in blocked_ids for record in records),
	}
	return {"items": [{"id": identifier, "count": max(0, int(counts[identifier]))} for identifier in INTERVENTION_ORDER]}


def _build_team_performance(
	teams: list[dict[str, Any]], records: list[dict[str, Any]], member_limit: int
) -> list[dict[str, Any]]:
	team_ids = {str(team.get("name")) for team in teams if team.get("name")}
	if not team_ids:
		return []
	staff_rows = _get_list(
		"CRM Staff",
		filters={"is_active": 1},
		fields=["name", "full_name", "user"],
		limit_page_length=0,
		warnings=None,
	)
	members: list[dict[str, Any]] = []
	for staff in staff_rows:
		staff_id = str(staff.get("name") or "")
		if not staff_id:
			continue
		memberships = _get_list(
			"CRM Team Membership",
			filters={"parent": staff_id, "parenttype": "CRM Staff", "team": ["in", list(team_ids)]},
			fields=["team", "function"],
			limit_page_length=0,
			warnings=None,
		)
		if not any(str(row.get("team")) in team_ids for row in memberships):
			continue
		members.append(staff)

	records_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for record in records:
		if record.get("owner_staff"):
			records_by_owner[str(record["owner_staff"])].append(record)
	result = []
	for member in members:
		staff_id = str(member["name"])
		owned = records_by_owner.get(staff_id, [])
		consulted = sum(bool(record.get("consulted_at")) for record in owned)
		admitted = sum(bool(record.get("admitted_at")) for record in owned)
		result.append(
			{
				"id": staff_id,
				"displayName": str(member.get("full_name") or member.get("user") or staff_id),
				"activeStudents": len(owned),
				"consulted": consulted,
				"admitted": admitted,
				"status": "needs-support"
				if consulted == 0 or (admitted / consulted) < 0.2
				else "on-track",
			}
		)
	result.sort(key=lambda row: (0 if row["status"] == "needs-support" else 1, -row["activeStudents"], row["id"]))
	return result[:member_limit]


def _build_student_status(records: list[dict[str, Any]]) -> dict[str, Any]:
	counts = {status: 0 for status in STUDENT_STATUS_ORDER}
	for record in records:
		status = record.get("status") if record.get("status") in counts else "new"
		counts[status] += 1
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


def _build_result_trend(
	records: list[dict[str, Any]], report_date: date, default_range: str, timezone: ZoneInfo
) -> dict[str, Any]:
	return {
		"defaultRange": default_range,
		"ranges": {
			"4w": _weekly_trend(records, report_date, timezone),
			"3m": _monthly_trend(records, report_date, timezone),
		},
	}


def _weekly_trend(records: list[dict[str, Any]], report_date: date, timezone: ZoneInfo) -> dict[str, Any]:
	week_start = report_date - timedelta(days=report_date.weekday()) - timedelta(days=21)
	points = []
	for index in range(4):
		start = week_start + timedelta(days=index * 7)
		end = min(start + timedelta(days=6), report_date)
		points.append(_trend_point(records, start, end, timezone, f"Tuần {index + 1}"))
	return {"from": week_start.isoformat(), "to": report_date.isoformat(), "points": points}


def _monthly_trend(records: list[dict[str, Any]], report_date: date, timezone: ZoneInfo) -> dict[str, Any]:
	starts = [_add_months(report_date, offset) for offset in (-3, -2, -1)]
	points = []
	for index, start in enumerate(starts):
		end = min(_add_months(start, 1) - timedelta(days=1), report_date)
		points.append(_trend_point(records, start, end, timezone, f"Tháng {index + 1}"))
	return {"from": starts[0].isoformat(), "to": report_date.isoformat(), "points": points}


def _trend_point(
	records: list[dict[str, Any]], start: date, end: date, timezone: ZoneInfo, label: str
) -> dict[str, Any]:
	return {
		"label": label,
		"periodStart": start.isoformat(),
		"periodEnd": end.isoformat(),
		"consulted": sum(sale_overview._date_inclusive(row.get("consulted_at"), start, end, timezone) for row in records),
		"admitted": sum(sale_overview._date_inclusive(row.get("admitted_at"), start, end, timezone) for row in records),
	}


def _annotate_tasks(tasks: list[dict[str, Any]], as_of: datetime, timezone: ZoneInfo) -> list[dict[str, Any]]:
	for task in tasks:
		due = sale_overview._as_timezone(sale_overview._coerce_datetime(task.get("due_at")), timezone)
		task["due_at"] = due
		task["is_overdue"] = bool(due and due < as_of and not _task_is_terminal(task))
	return tasks


def _task_is_terminal(task: dict[str, Any]) -> bool:
	return task.get("status") in TERMINAL_TASK_STATUSES


def _is_assigned(record: dict[str, Any]) -> bool:
	return bool(record.get("owner_staff"))


def _team_meta(teams: list[dict[str, Any]]) -> dict[str, str]:
	if not teams:
		return {"id": "", "name": "Đội Sale hiện tại"}
	if len(teams) == 1:
		return {"id": str(teams[0].get("name") or ""), "name": str(teams[0].get("team_name") or teams[0].get("name") or "")}
	return {"id": ",".join(str(team.get("name")) for team in teams), "name": "Các đội Sale hiện tại"}


def _viewer(user: str) -> dict[str, str]:
	display_name = frappe.db.get_value("User", user, "full_name") or user
	return {"id": str(user), "displayName": str(display_name)}


def _now(timezone: ZoneInfo) -> datetime:
	now = frappe.utils.now_datetime()
	parsed = sale_overview._as_timezone(sale_overview._coerce_datetime(now), timezone)
	return parsed or datetime.now(timezone)


def _date_of(value: Any) -> date | None:
	parsed = sale_overview._coerce_datetime(value)
	return parsed.date() if parsed else None


def _add_months(value: date, months: int) -> date:
	month_index = value.month - 1 + months
	year = value.year + month_index // 12
	month = month_index % 12 + 1
	return date(year, month, min(value.day, calendar.monthrange(year, month)[1]))


def _year_number(value: Any) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return 0


def _has_warning(warnings: list[str], key: str) -> bool:
	return any(item.startswith(f"{key}.") for item in warnings)
