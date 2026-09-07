"""Permission-scoped overview API for the Lead Sale dashboard.

The endpoint builds one snapshot from the current Lead Sale permission scope.
The browser may choose presentation options (date, timezone, trend range and
member limit), but it cannot choose a team, owner or student scope.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import cmp_to_key
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

ASSIGNMENT_POLICY_VERSION = "student-assignment-r1"
ASSIGNMENT_FILTERS = {"all", "assigned", "review", "no_match", "missing_data", "error"}
ASSIGNMENT_SORTS = {"receivedAt", "name", "status", "owner", "matchScore"}
ASSIGNMENT_ORDERS = {"asc", "desc"}
ASSIGNMENT_PIPELINE_REQUEST_STATUSES = {"pending", "deferred"}
ASSIGNMENT_OWNER_FUNCTIONS = {"Sale", "CTV Sale"}
ASSIGNMENT_STUDENT_FIELDS = [
	"name",
	"student_name",
	"high_school",
	"province",
	"major",
	"aspiration",
	"source",
	"creation",
	"owner_staff",
	"assigned_to",
	"owning_team",
	"owning_pool",
	"latest_score",
	"ownership_revision",
	"admission_year",
	"lifecycle_stage",
]
ASSIGNMENT_WORKFLOW_CONNECTIONS = (
	{"source": "input", "target": "validation", "label": None},
	{"source": "validation", "target": "classification", "label": "Hàng chờ hợp lệ"},
	{"source": "classification", "target": "matching", "label": "Xác định khu vực"},
	{"source": "classification", "target": "review", "label": "Thiếu hoặc sai dữ liệu"},
	{"source": "matching", "target": "assignment", "label": "Đủ điều kiện gán"},
	{"source": "matching", "target": "review", "label": "Chờ xử lý"},
	{"source": "review", "target": "assignment", "label": "Đã bổ sung"},
)
ASSIGNMENT_WORKFLOW_DEFINITIONS = (
	(
		"input",
		"Lead vào hệ thống",
		"Tạo Lead · hàng chờ theo cơ sở",
		"Tiếp nhận Lead, chống trùng và đưa vào hàng chờ theo cơ sở.",
		("Kiểm tra Lead trùng trước khi đưa vào đợt.", "Chỉ chạy khi người vận hành bấm Sắp xếp tự động."),
	),
	(
		"validation",
		"Xác định hàng chờ",
		"Cơ sở · Nhóm · Hàng chờ",
		"Xác định đúng hàng chờ đang hoạt động và khớp cơ sở của Lead.",
		("Hàng chờ phải đang hoạt động và thuộc đúng cơ sở.", "Sai cấu hình: dừng để kiểm tra lại."),
	),
	(
		"classification",
		"Xác định khu vực",
		"Trường → Khu vực → Tỉnh",
		"Xác định địa bàn theo thứ tự ưu tiên của trường học, khu vực và tỉnh.",
		("Ưu tiên nhân sự được gán trực tiếp cho trường.", "Không có khu vực: đưa vào hàng chờ theo tỉnh."),
	),
	(
		"matching",
		"Chọn người phụ trách",
		"Trường · Khu vực · Hàng chờ",
		"Chọn người còn chỗ nhận theo cách chia đã thiết lập.",
		("Ưu tiên nhân sự gán trực tiếp cho trường.", "Nếu không có, chọn nhân sự trong nhóm của khu vực."),
	),
	(
		"review",
		"Trường hợp cần kiểm tra",
		"Thiếu dữ liệu · Hết chỗ · Chờ xử lý",
		"Lead chưa thể gán sẽ được giữ lại để bổ sung dữ liệu hoặc xử lý sau.",
		("Bổ sung trường, khu vực hoặc tỉnh còn thiếu.", "Chỉ chạy lại khi dữ liệu hoặc cấu hình đã được sửa."),
	),
	(
		"assignment",
		"Ghi nhận kết quả",
		"Người phụ trách · Nhóm · Lịch sử",
		"Lưu người được gán, nhóm, khu vực và lý do để tra cứu về sau.",
		("Không sửa trực tiếp dữ liệu phân công ngoài luồng này.", "Mỗi kết quả có lịch sử và mã đợt phân công."),
	),
)

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
	"""Return one consistent, permission-scoped Lead Sale snapshot."""
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
			"Bạn cần đăng nhập để truy cập tổng quan Lead Sale.",
			frappe.AuthenticationError,
			401,
		)
	if user != "Administrator" and frappe.db.get_value("User", user, "enabled") not in (1, True, "1"):
		raise_api_error("UNAUTHENTICATED", "Tài khoản không hoạt động.", frappe.AuthenticationError, 401)
	profile = resolve_crm_profile(set(frappe.get_roles(user)))
	if profile != "lead_sales":
		raise_api_error(
			"FORBIDDEN",
			"Bạn không có quyền truy cập tổng quan Lead Sale.",
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
	memberships = _get_all(
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
			"CRM Lead",
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


def _get_all(
	doctype: str,
	*,
	filters: dict[str, Any],
	fields: list[str],
	limit_page_length: int,
	warnings: list[str] | None,
	warning_key: str | None = None,
	order_by: str | None = None,
) -> list[Any]:
	"""Read child-table projections without standalone DocType permissions."""
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
		return list(frappe.get_all(doctype, **kwargs))
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
		memberships = _get_all(
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


def _assignment_date_active(row: dict[str, Any], today: date | None = None) -> bool:
	today = today or frappe.utils.getdate()
	start = row.get("effective_from")
	end = row.get("effective_until")
	return (not start or frappe.utils.getdate(start) <= today) and (
		not end or frappe.utils.getdate(end) >= today
	)


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


# Student assignment workspace -------------------------------------------------
#
# This projection intentionally lives beside the existing Lead Sale overview
# methods. It is a read model over the canonical Student ownership fields and
# routing/ownership evidence; it does not create a parallel assignment table.


def _require_assignment_access() -> dict[str, str]:
	return _require_access()


def _parse_assignment_page(value: Any) -> int:
	if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value or "").strip()):
		raise_api_error("INVALID_QUERY", "Tham số page không hợp lệ.", frappe.ValidationError, 400)
	page = int(value)
	if page < 1:
		raise_api_error("INVALID_QUERY", "Tham số page không hợp lệ.", frappe.ValidationError, 400)
	return page


def _parse_assignment_query(
	filter: str = "all",
	q: str = "",
	page: str | int = 1,
	pageSize: str | int = 20,
	sort: str = "receivedAt",
	order: str = "desc",
) -> dict[str, Any]:
	filter_value = str(filter or "all").strip().lower()
	if filter_value not in ASSIGNMENT_FILTERS:
		raise_api_error("INVALID_QUERY", "Tham số filter không hợp lệ.", frappe.ValidationError, 400)
	search = str(q or "").strip()
	if len(search) > 140:
		raise_api_error("INVALID_QUERY", "Tham số q không hợp lệ.", frappe.ValidationError, 400)
	page_value = _parse_assignment_page(page)
	page_size = parse_limit(pageSize, field="pageSize", minimum=1, maximum=100, default=20)
	sort_value = str(sort or "receivedAt").strip()
	if sort_value not in ASSIGNMENT_SORTS:
		raise_api_error("INVALID_QUERY", "Tham số sort không hợp lệ.", frappe.ValidationError, 400)
	order_value = str(order or "desc").strip().lower()
	if order_value not in ASSIGNMENT_ORDERS:
		raise_api_error("INVALID_QUERY", "Tham số order không hợp lệ.", frappe.ValidationError, 400)
	return {
		"filter": filter_value,
		"q": search,
		"page": page_value,
		"page_size": page_size,
		"sort": sort_value,
		"order": order_value,
	}


def _assignment_scope(user: str, warnings: list[str]) -> dict[str, Any]:
	teams = _resolve_teams(user, warnings)
	team_ids = sorted({str(team.get("name")) for team in teams if team.get("name")})
	if not team_ids:
		warnings.append("team.scope_empty")
		return {"teams": teams, "team_ids": [], "staff_ids": [], "memberships": []}
	memberships = _get_all(
		"CRM Team Membership",
		filters={"team": ["in", team_ids], "parenttype": "CRM Staff"},
		fields=["parent as staff", "team", "function", "effective_from", "effective_until"],
		limit_page_length=0,
		warnings=warnings,
		warning_key="team",
	)
	memberships = [row for row in memberships if _assignment_date_active(row)]
	staff_ids = sorted({str(row.get("staff")) for row in memberships if row.get("staff")})
	return {
		"teams": teams,
		"team_ids": team_ids,
		"staff_ids": staff_ids,
		"memberships": memberships,
	}


def _assignment_load_students(
	scope: dict[str, Any], admission_year: str | None, warnings: list[str]
) -> list[dict[str, Any]]:
	team_ids = scope.get("team_ids") or []
	staff_ids = scope.get("staff_ids") or []
	if not team_ids and not staff_ids:
		return []
	try:
		if not frappe.db.table_exists("CRM Lead"):
			warnings.append("students.source_unavailable")
			return []
		filters = {"lifecycle_stage": ["!=", "Lost"]}
		if admission_year:
			filters["admission_year"] = admission_year
		return [
			dict(row)
			for row in frappe.get_list(
				"CRM Lead",
				filters=filters,
				or_filters=[
					["owner_staff", "in", staff_ids or ["__no_staff__"]],
					["owning_team", "in", team_ids or ["__no_team__"]],
				],
				fields=ASSIGNMENT_STUDENT_FIELDS,
				order_by="name asc",
				limit_page_length=0,
			)
		]
	except Exception:
		warnings.append("students.source_unavailable")
		return []


def _assignment_lookup(
	doctype: str, names: set[str], label_field: str, warnings: list[str]
) -> dict[str, str]:
	keys = sorted({str(name) for name in names if name})
	if not keys:
		return {}
	rows = _get_list(
		doctype,
		filters={"name": ["in", keys]},
		fields=["name", label_field],
		limit_page_length=0,
		warnings=warnings,
		warning_key=f"lookup.{doctype.lower().replace(' ', '_')}",
	)
	return {str(row.get("name")): str(row.get(label_field) or row.get("name")) for row in rows if row.get("name")}


def _assignment_metadata(student_ids: list[str], warnings: list[str]) -> dict[str, Any]:
	if not student_ids:
		return {"events": {}, "routing": {}}
	events = _get_list(
		"CRM Student Ownership Event",
		filters={"student": ["in", student_ids]},
		fields=[
			"name",
			"event_id",
			"event_type",
			"student",
			"actor",
			"prior_owner_staff",
			"next_owner_staff",
			"reason",
			"route_trigger",
			"event_at",
			"occurred_at",
		],
		limit_page_length=0,
		warnings=warnings,
		warning_key="assignment_events",
		order_by="event_at asc, creation asc, name asc",
	)
	routing_rows = _get_all(
		"CRM Student Routing Request",
		filters={"student": ["in", student_ids]},
		fields=[
			"name",
			"student",
			"status",
			"last_error_code",
			"creation",
			"completed_at",
			"revision",
		],
		limit_page_length=0,
		warnings=warnings,
		warning_key="routing",
		order_by="creation asc, name asc",
	)
	events_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in events:
		if row.get("student"):
			events_by_student[str(row["student"])].append(dict(row))
	routing_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in routing_rows:
		if row.get("student"):
			routing_by_student[str(row["student"])].append(dict(row))
	return {
		"events": events_by_student,
		"routing": routing_by_student,
	}


def _assignment_latest_event(metadata: dict[str, Any], student_id: str) -> dict[str, Any] | None:
	rows = metadata.get("events", {}).get(student_id) or []
	return rows[-1] if rows else None


def _assignment_latest_routing(metadata: dict[str, Any], student_id: str) -> dict[str, Any] | None:
	rows = metadata.get("routing", {}).get(student_id) or []
	return rows[-1] if rows else None


def _assignment_status(row: dict[str, Any], metadata: dict[str, Any]) -> str:
	if row.get("owner_staff") or row.get("assigned_to"):
		return "assigned"
	routing = _assignment_latest_routing(metadata, str(row.get("name") or ""))
	if routing and (routing.get("status") == "failed" or routing.get("last_error_code")):
		return "error"
	if not row.get("province"):
		return "missing_data"
	return "no_match"


def _assignment_method(row: dict[str, Any], event: dict[str, Any] | None, actor: str) -> str:
	if not event:
		return "automatic"
	if event.get("route_trigger"):
		return "automatic"
	return "manual" if str(event.get("actor") or "") == actor else "automatic"


def _assignment_revision(row: dict[str, Any]) -> int:
	try:
		return max(0, int(row.get("ownership_revision") or 0))
	except (TypeError, ValueError):
		return 0


def _assignment_reason(
	row: dict[str, Any], status: str, event: dict[str, Any] | None, routing: dict[str, Any] | None
) -> str | None:
	if event and event.get("reason"):
		return str(event["reason"])
	if status == "missing_data":
		return "Thiếu khu vực để xác định người phụ trách."
	if status == "error":
		return str(routing.get("last_error_code") or "Không thể hoàn tất phân công tự động.") if routing else "Không thể hoàn tất phân công tự động."
	if status == "no_match":
		return "Không có Sale đạt ngưỡng phù hợp tối thiểu."
	return None


def _assignment_item(
	row: dict[str, Any],
	lookups: dict[str, dict[str, str]],
	metadata: dict[str, Any],
	actor: str,
	timezone: ZoneInfo,
	as_of: datetime,
	warnings: list[str],
) -> dict[str, Any]:
	student_id = str(row.get("name") or "")
	status = _assignment_status(row, metadata)
	event = _assignment_latest_event(metadata, student_id)
	routing = _assignment_latest_routing(metadata, student_id)
	received_at = sale_overview._as_timezone(sale_overview._coerce_datetime(row.get("creation")), timezone)
	if not received_at:
		warnings.append("students.received_at_missing")
		received_at = as_of
	owner_id = row.get("owner_staff") or row.get("assigned_to")
	owner_id = str(owner_id) if owner_id else None
	owner = (
		{"id": owner_id, "displayName": lookups.get("owners", {}).get(owner_id, owner_id)}
		if owner_id
		else None
	)
	match_score = row.get("latest_score")
	try:
		match_score = max(0, min(100, round(float(match_score)))) if match_score is not None else None
	except (TypeError, ValueError):
		match_score = None
	return {
		"studentId": student_id,
		"name": str(row.get("student_name") or student_id),
		"school": lookups.get("schools", {}).get(str(row.get("high_school") or ""), row.get("high_school") or ""),
		"region": lookups.get("provinces", {}).get(str(row.get("province") or ""), row.get("province")) or None,
		"interest": lookups.get("majors", {}).get(str(row.get("major") or ""), row.get("major") or row.get("aspiration")) or None,
		"source": lookups.get("sources", {}).get(str(row.get("source") or ""), row.get("source")) or None,
		"receivedAt": received_at.isoformat(timespec="seconds"),
		"status": status,
		"owner": owner,
		"matchScore": match_score,
		"method": _assignment_method(row, event, actor),
		"reason": _assignment_reason(row, status, event, routing),
		"revision": _assignment_revision(row),
		"executionId": (
			str(routing.get("name"))
			if routing and routing.get("name")
			else (str(event.get("event_id") or event.get("name")) if event else None)
		),
	}


def _assignment_fold(value: Any) -> str:
	text = unicodedata.normalize("NFKD", str(value or "").casefold())
	return "".join(char for char in text if not unicodedata.combining(char)).replace("đ", "d")


def _assignment_matches(item: dict[str, Any], query: str) -> bool:
	if not query:
		return True
	needle = _assignment_fold(query)
	owner = item.get("owner") or {}
	return needle in _assignment_fold(
		" ".join(
			str(item.get(field) or "")
			for field in ("studentId", "name", "school")
		)
		+ " "
		+ str(owner.get("displayName") or "")
	)


def _assignment_filter_matches(item: dict[str, Any], filter_value: str) -> bool:
	if filter_value == "all":
		return True
	if filter_value == "assigned":
		return item["status"] == "assigned" and bool(item.get("owner"))
	if filter_value == "review":
		return not item.get("owner")
	return item["status"] == filter_value


def _assignment_compare(left: dict[str, Any], right: dict[str, Any], sort: str, order: str) -> int:
	if sort == "receivedAt":
		left_value, right_value = left.get("receivedAt"), right.get("receivedAt")
	elif sort == "name":
		left_value, right_value = _assignment_fold(left.get("name")), _assignment_fold(right.get("name"))
	elif sort == "status":
		left_value, right_value = left.get("status"), right.get("status")
	elif sort == "owner":
		left_value = _assignment_fold((left.get("owner") or {}).get("displayName"))
		right_value = _assignment_fold((right.get("owner") or {}).get("displayName"))
	else:
		left_value, right_value = left.get("matchScore"), right.get("matchScore")
	if left_value is None and right_value is not None:
		return 1
	if left_value is not None and right_value is None:
		return -1
	if left_value != right_value:
		if order == "desc":
			return -1 if left_value > right_value else 1
		return -1 if left_value < right_value else 1
	left_id, right_id = str(left.get("studentId") or ""), str(right.get("studentId") or "")
	return -1 if left_id < right_id else 1 if left_id > right_id else 0


def _assignment_workflow(summary: dict[str, Any], health: dict[str, Any]) -> dict[str, Any]:
	received = int(summary["received"])
	assigned = int(summary["assigned"])
	pending = int(summary["pending"])
	missing = int(summary["byStatus"]["missing_data"])
	error = int(summary["byStatus"]["error"])
	metrics = {
		"input": (received, received, 0, 0),
		"validation": (received, max(0, received - missing), missing, 0),
		"classification": (max(0, received - missing), max(0, received - missing), 0, 0),
		"matching": (max(0, received - missing), assigned, max(0, pending - error), error),
		"review": (pending, 0, pending, 0),
		"assignment": (received, assigned, max(0, pending - error), error),
	}
	statuses = {
		"input": "success",
		"validation": "warning" if missing else "success",
		"classification": "success",
		"matching": "error" if error else "warning" if pending else "success",
		"review": "warning" if pending else "success",
		"assignment": "error" if error else "warning" if pending else "success",
	}
	steps = []
	for order, (step_id, title, description, detail, rules) in enumerate(ASSIGNMENT_WORKFLOW_DEFINITIONS, start=1):
		processed, success, warning, step_error = metrics[step_id]
		steps.append(
			{
				"id": step_id,
				"order": order,
				"title": title,
				"description": description,
				"detail": detail,
				"rules": list(rules),
				"status": statuses[step_id],
				"metrics": {
					"processedCount": max(0, processed),
					"successCount": max(0, success),
					"warningCount": max(0, warning),
					"errorCount": max(0, step_error),
				},
			}
		)
	return {
		"mode": "live",
		"version": ASSIGNMENT_POLICY_VERSION,
		"steps": steps,
		"connections": [dict(connection) for connection in ASSIGNMENT_WORKFLOW_CONNECTIONS],
	}


def _assignment_pipeline_candidates(
	students: list[dict[str, Any]], routing_rows: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
	"""Select unassigned pool-owned Students without broadening the caller scope."""
	latest_request_by_student: dict[str, dict[str, Any]] = {}
	request_rank_by_student: dict[str, int] = {}
	for index, row in enumerate(routing_rows):
		student_id = str(row.get("student") or "")
		if student_id and student_id not in latest_request_by_student:
			latest_request_by_student[student_id] = row
			request_rank_by_student[student_id] = index

	candidates = []
	for student in students:
		student_id = str(student.get("name") or "")
		if not student_id or student.get("owner_staff") or student.get("assigned_to") or not student.get("owning_pool"):
			continue
		request = latest_request_by_student.get(student_id)
		if request and request.get("status") not in ASSIGNMENT_PIPELINE_REQUEST_STATUSES:
			continue
		candidates.append({"student": student, "request": request})
	candidates.sort(
		key=lambda row: (
			0 if row["request"] else 1,
			request_rank_by_student.get(str(row["student"].get("name") or ""), len(routing_rows)),
			str(row["student"].get("name") or ""),
		)
	)
	return candidates[:limit]


def _assignment_pipeline_run_result(
	student: dict[str, Any], request_name: str | None, result: dict[str, Any]
) -> dict[str, Any]:
	return {
		"student": str(student.get("name") or ""),
		"request": request_name or result.get("request"),
		"status": result.get("status") or "failed",
		"tier": result.get("tier"),
		"queue": result.get("queue"),
		"ownerStaff": result.get("owner_staff"),
		"reason": result.get("reason"),
		"errorCode": result.get("error_code"),
	}


@frappe.whitelist(methods=["POST"])
def run_student_assignment_pipeline(
	admissionYear: str | int | None = None,
	timezone: str = DEFAULT_TIMEZONE,
	limit: str | int = 50,
) -> dict[str, Any]:
	"""Run eligible pool-owned Students through the canonical routing worker.

	The endpoint is deliberately scoped to the current Lead Sale team and never
	passes an already-owned Student to the routing service. Deferred requests are
	retried, pending requests are processed, and pool-owned Students without a
	request receive one before processing.
	"""
	access = _require_assignment_access()
	report_timezone = _parse_timezone(timezone)
	year = _resolve_admission_year(admissionYear)
	page_limit = parse_limit(limit, field="limit", minimum=1, maximum=100, default=50)
	warnings: list[str] = []
	started_at = _now(report_timezone)
	run_id = f"assignment-pipeline-{uuid.uuid4().hex}"

	if not frappe.db.table_exists("CRM Student Routing Request"):
		raise_api_error(
			"ROUTING_UNAVAILABLE",
			"CRM Student Routing Request chưa được cài đặt.",
			frappe.ValidationError,
			503,
		)

	scope = _assignment_scope(access["user"], warnings)
	students = _assignment_load_students(scope, year, warnings)
	student_ids = [str(row.get("name")) for row in students if row.get("name")]
	routing_rows = (
		[
			dict(row)
			for row in frappe.get_all(
				"CRM Student Routing Request",
				filters={"student": ["in", student_ids or ["__no_student__"]]},
				fields=["name", "student", "status", "last_error_code", "creation"],
				order_by="creation desc, name desc",
				limit_page_length=0,
			)
		]
		if student_ids
		else []
	)
	candidates = _assignment_pipeline_candidates(students, routing_rows, page_limit)

	from crm.fcrm.student_routing import (
		enqueue_student_routing,
		process_routing_request,
		retry_student_routing,
	)

	results: list[dict[str, Any]] = []
	for candidate in candidates:
		student = candidate["student"]
		request = candidate.get("request")
		request_name = str(request.get("name")) if request and request.get("name") else None
		try:
			if not request_name:
				request = enqueue_student_routing(
					str(student["name"]),
					trigger="pool_entry",
					correlation_id=f"{run_id}:{student['name']}",
				)
				request_name = str(request.name)
			if request and request.get("status") == "deferred":
				result = retry_student_routing(request_name)
			else:
				result = process_routing_request(request_name)
			results.append(_assignment_pipeline_run_result(student, request_name, result))
		except Exception as exc:
			frappe.db.rollback()
			results.append(
				_assignment_pipeline_run_result(
					student,
					request_name,
					{
						"status": "failed",
						"error_code": getattr(exc, "code", None) or getattr(exc, "error_code", None),
						"reason": str(exc),
					},
				)
			)

	completed_at = _now(report_timezone)
	assigned = sum(row["status"] == "applied" for row in results)
	deferred = sum(row["status"] in {"deferred", "queued"} for row in results)
	failed = sum(row["status"] == "failed" for row in results)
	run = {
		"id": run_id,
		"status": "completed" if not failed else "completed_with_errors",
		"startedAt": started_at.isoformat(timespec="seconds"),
		"completedAt": completed_at.isoformat(timespec="seconds"),
		"checked": len(candidates),
		"assigned": assigned,
		"deferred": deferred,
		"failed": failed,
		"skipped": max(0, len(students) - len(candidates)),
	}

	snapshot = get_student_assignment_workspace(
		admissionYear=year,
		timezone=timezone,
		page=1,
		pageSize=1,
	)
	workflow = dict(snapshot["workflow"])
	workflow["lastRun"] = run
	return {
		"meta": snapshot["meta"],
		"summary": snapshot["summary"],
		"health": snapshot["health"],
		"workflow": workflow,
		"run": run,
		"results": results,
	}


def _assignment_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
	by_status = {status: 0 for status in ("assigned", "no_match", "missing_data", "error")}
	for item in items:
		if item["status"] in by_status:
			by_status[item["status"]] += 1
	assigned = by_status["assigned"]
	pending = len(items) - assigned
	return {"received": len(items), "assigned": assigned, "pending": pending, "byStatus": by_status}


def _assignment_health(summary: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
	received = summary["received"]
	automatic_assigned = sum(item["status"] == "assigned" and item["method"] == "automatic" for item in items)
	return {
		"automationEnabled": True,
		"automationRate": round(automatic_assigned / received * 100, 1) if received else None,
		"successRate": round(summary["assigned"] / received * 100, 1) if received else None,
		"reviewCount": summary["pending"],
		"errorCount": summary["byStatus"]["error"],
		"averageProcessingMs": None,
		"policyVersion": ASSIGNMENT_POLICY_VERSION,
	}


def _assignment_team_meta(teams: list[dict[str, Any]]) -> dict[str, str]:
	if not teams:
		return {"id": "", "name": "Đội Sale hiện tại"}
	if len(teams) == 1:
		return {
			"id": str(teams[0].get("name") or ""),
			"name": str(teams[0].get("team_name") or teams[0].get("name") or ""),
		}
	return {
		"id": ",".join(str(team.get("name")) for team in teams),
		"name": "Các đội Sale hiện tại",
	}


def _assignment_base_response(
	access: dict[str, str],
	scope: dict[str, Any],
	admission_year: str,
	report_date: date,
	timezone: ZoneInfo,
	as_of: datetime,
	warnings: list[str],
	items: list[dict[str, Any]],
) -> dict[str, Any]:
	summary = _assignment_summary(items)
	health = _assignment_health(summary, items)
	return {
		"meta": {
			"viewer": _viewer(access["user"]),
			"team": _assignment_team_meta(scope.get("teams") or []),
			"admissionYear": _year_number(admission_year),
			"date": report_date.isoformat(),
			"asOf": as_of.isoformat(timespec="seconds"),
			"timezone": getattr(timezone, "key", str(timezone)),
			"status": "unavailable" if _has_warning(warnings, "students") else "partial" if warnings else "available",
			"warnings": sorted(set(warnings)),
		},
		"summary": summary,
		"health": health,
		"workflow": _assignment_workflow(summary, health),
		"items": items,
	}


@frappe.whitelist(methods=["GET"])
def get_student_assignment_workspace(
	admissionYear: str | int | None = None,
	date: str | None = None,
	timezone: str = DEFAULT_TIMEZONE,
	filter: str = "all",
	q: str = "",
	page: str | int = 1,
	pageSize: str | int = 20,
	sort: str = "receivedAt",
	order: str = "desc",
) -> dict[str, Any]:
	"""Return one permission-scoped Student assignment snapshot."""
	access = _require_assignment_access()
	report_timezone = _parse_timezone(timezone)
	report_date = _parse_report_date(date, report_timezone)
	admission_year = _resolve_admission_year(admissionYear)
	query = _parse_assignment_query(filter, q, page, pageSize, sort, order)
	warnings: list[str] = []
	as_of = _now(report_timezone)
	scope = _assignment_scope(access["user"], warnings)
	students = _assignment_load_students(scope, admission_year, warnings)
	student_ids = [str(row.get("name")) for row in students if row.get("name")]
	lookups = {
		"schools": _assignment_lookup("CRM High School", {str(row.get("high_school")) for row in students}, "school_name", warnings),
		"provinces": _assignment_lookup("CRM Province", {str(row.get("province")) for row in students}, "province_name", warnings),
		"majors": _assignment_lookup("CRM Major", {str(row.get("major")) for row in students}, "major_name", warnings),
		"sources": _assignment_lookup("CRM Lead Source", {str(row.get("source")) for row in students}, "source_name", warnings),
		"owners": _assignment_lookup("CRM Staff", {str(row.get("owner_staff") or row.get("assigned_to")) for row in students}, "full_name", warnings),
	}
	metadata = _assignment_metadata(student_ids, warnings)
	all_items = [
		_assignment_item(row, lookups, metadata, access["user"], report_timezone, as_of, warnings)
		for row in students
	]
	filtered = [
		item
		for item in all_items
		if _assignment_filter_matches(item, query["filter"]) and _assignment_matches(item, query["q"])
	]
	filtered.sort(key=cmp_to_key(lambda left, right: _assignment_compare(left, right, query["sort"], query["order"])))
	start = (query["page"] - 1) * query["page_size"]
	page_items = filtered[start : start + query["page_size"]]
	response = _assignment_base_response(
		access,
		scope,
		admission_year,
		report_date,
		report_timezone,
		as_of,
		warnings,
		all_items,
	)
	total = len(filtered)
	response["items"] = page_items
	response["pagination"] = {
		"page": query["page"],
		"pageSize": query["page_size"],
		"total": total,
		"totalPages": (total + query["page_size"] - 1) // query["page_size"] if total else 0,
		"hasNextPage": start + len(page_items) < total,
	}
	return response


@frappe.whitelist(methods=["GET"])
def get_lead_assignment_workspace(**kwargs: Any) -> dict[str, Any]:
	"""Canonical Lead-named alias for the assignment workspace contract."""
	# Frappe injects the routed method name as ``cmd`` for RPC calls.  The
	# Student-named implementation intentionally accepts only workspace query
	# parameters, so do not forward this framework argument to it.
	kwargs.pop("cmd", None)
	return get_student_assignment_workspace(**kwargs)


def _assignment_find_student(
	student_id: str, admission_year: str | None, scope: dict[str, Any], warnings: list[str]
) -> dict[str, Any]:
	students = _assignment_load_students(scope, admission_year, warnings)
	row = next((row for row in students if str(row.get("name")) == student_id), None)
	if not row:
		raise_api_error("STUDENT_NOT_FOUND", "Không tìm thấy Lead.", frappe.DoesNotExistError, 404)
	return row


def _assignment_issue(item: dict[str, Any]) -> dict[str, Any] | None:
	if item["status"] == "assigned":
		return None
	if item["status"] == "missing_data":
		return {
			"code": "MISSING_DATA",
			"message": "Thiếu khu vực của Lead nên chưa thể tìm người phù hợp.",
			"missingFields": ["region"],
		}
	if item["status"] == "error":
		return {
			"code": "ASSIGNMENT_ERROR",
			"message": item.get("reason") or "Không thể hoàn tất phân công tự động.",
			"missingFields": [],
		}
	return {
		"code": "NO_MATCH",
		"message": "Chưa có nhân sự đạt điều kiện phụ trách khu vực này.",
		"missingFields": [],
	}


def _assignment_owner_candidates(
	student: dict[str, Any], scope: dict[str, Any], all_students: list[dict[str, Any]], warnings: list[str]
) -> list[dict[str, Any]]:
	team_ids = set(scope.get("team_ids") or [])
	if not team_ids:
		return []
	staff_rows = _get_list(
		"CRM Staff",
		filters={"is_active": 1},
		fields=["name", "full_name", "user", "is_active", "campus"],
		limit_page_length=0,
		warnings=warnings,
		warning_key="candidates",
	)
	memberships = [
		row
		for row in (scope.get("memberships") or [])
		if row.get("team") in team_ids and row.get("function") in ASSIGNMENT_OWNER_FUNCTIONS
	]
	memberships_by_staff: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in memberships:
		if row.get("staff"):
			memberships_by_staff[str(row["staff"])].append(row)
	active_counts = defaultdict(int)
	for row in all_students:
		if row.get("owner_staff") or row.get("assigned_to"):
			active_counts[str(row.get("owner_staff") or row.get("assigned_to"))] += 1
	capacity_rows = _get_list(
		"CRM Staff Capacity Period",
		filters={"staff": ["in", sorted(memberships_by_staff)]},
		fields=["staff", "max_active_students", "approved", "period_start", "period_end"],
		limit_page_length=0,
		warnings=warnings,
		warning_key="capacity",
	)
	capacity_by_staff: dict[str, dict[str, Any]] = {}
	for row in capacity_rows:
		if not row.get("staff") or not row.get("approved") or not _assignment_date_active(
			{"effective_from": row.get("period_start"), "effective_until": row.get("period_end")}
		):
			continue
		if row.get("max_active_students") is None:
			continue
		staff_key = str(row["staff"])
		previous = capacity_by_staff.get(staff_key)
		if not previous or str(row.get("period_start") or "") > str(previous.get("period_start") or ""):
			capacity_by_staff[staff_key] = dict(row)
	staff_by_id = {str(row.get("name")): row for row in staff_rows if row.get("name")}
	region_present = bool(student.get("province"))
	result = []
	for staff_id in sorted(memberships_by_staff):
		staff = staff_by_id.get(staff_id)
		if not staff or not staff.get("is_active"):
			continue
		user = staff.get("user")
		if not user or frappe.db.get_value("User", user, "enabled") not in (1, True, "1"):
			continue
		profile = resolve_crm_profile(frappe.get_roles(user))
		if profile not in {"sales", "ctv_sale"}:
			continue
		active = max(0, int(active_counts.get(staff_id, 0)))
		capacity = capacity_by_staff.get(staff_id, {}).get("max_active_students")
		try:
			capacity = max(0, int(capacity)) if capacity is not None else 0
		except (TypeError, ValueError):
			capacity = 0
		remaining = max(0, capacity - active)
		eligible = bool(region_present and capacity > active)
		reasons = []
		if not region_present:
			reasons.append("Thiếu khu vực để đánh giá phạm vi phụ trách.")
		if capacity <= active:
			reasons.append("Đã đạt sức chứa hiện tại của nhân sự.")
		result.append(
			{
				"id": staff_id,
				"displayName": str(staff.get("full_name") or staff_id),
				"activeStudents": active,
				"capacity": capacity,
				"remainingCapacity": remaining,
				"matchScore": 70 if region_present else 0,
				"eligible": eligible,
				"reasons": reasons,
			}
		)
	result.sort(key=lambda row: (-int(row["matchScore"]), -int(row["remainingCapacity"]), row["id"]))
	return result[:3]


def _assignment_detail_events(
	metadata: dict[str, Any], student_id: str, owner_lookup: dict[str, str]
) -> list[dict[str, Any]]:
	rows = []
	for event in metadata.get("events", {}).get(student_id) or []:
		actor_id = str(event.get("actor") or "") or None
		from_owner = str(event.get("prior_owner_staff") or "") or None
		to_owner = str(event.get("next_owner_staff") or "") or None
		rows.append(
			{
				"eventId": str(event.get("event_id") or event.get("name") or ""),
				"type": str(event.get("event_type") or "assignment"),
				"actor": {"id": actor_id, "displayName": actor_id} if actor_id else None,
				"fromOwner": {"id": from_owner, "displayName": owner_lookup.get(from_owner, from_owner)} if from_owner else None,
				"toOwner": {"id": to_owner, "displayName": owner_lookup.get(to_owner, to_owner)} if to_owner else None,
				"reason": event.get("reason"),
				"occurredAt": str(event.get("occurred_at") or event.get("event_at") or ""),
			}
		)
	return rows


@frappe.whitelist(methods=["GET"])
def get_student_assignment_detail(
	studentId: str | None = None, admissionYear: str | int | None = None
) -> dict[str, Any]:
	"""Return one scoped assignment record with candidates and rule evidence."""
	access = _require_assignment_access()
	student_id = str(studentId or "").strip()
	if not student_id or len(student_id) > 140:
		raise_api_error("INVALID_QUERY", "studentId là bắt buộc.", frappe.ValidationError, 400)
	admission_year = _resolve_admission_year(admissionYear)
	warnings: list[str] = []
	scope = _assignment_scope(access["user"], warnings)
	student = _assignment_find_student(student_id, admission_year, scope, warnings)
	report_timezone = ZoneInfo(DEFAULT_TIMEZONE)
	as_of = _now(report_timezone)
	metadata = _assignment_metadata([student_id], warnings)
	owner_ids = {str(student.get("owner_staff") or student.get("assigned_to"))}
	for event in metadata.get("events", {}).get(student_id) or []:
		owner_ids.update(str(event.get(field)) for field in ("prior_owner_staff", "next_owner_staff") if event.get(field))
	lookups = {
		"schools": _assignment_lookup("CRM High School", {str(student.get("high_school"))}, "school_name", warnings),
		"provinces": _assignment_lookup("CRM Province", {str(student.get("province"))}, "province_name", warnings),
		"majors": _assignment_lookup("CRM Major", {str(student.get("major"))}, "major_name", warnings),
		"sources": _assignment_lookup("CRM Lead Source", {str(student.get("source"))}, "source_name", warnings),
		"owners": _assignment_lookup("CRM Staff", owner_ids, "full_name", warnings),
	}
	item = _assignment_item(student, lookups, metadata, access["user"], report_timezone, as_of, warnings)
	all_students = _assignment_load_students(scope, admission_year, warnings)
	candidates = _assignment_owner_candidates(student, scope, all_students, warnings)
	explainability_reason = item.get("reason") or "Không có nhân sự đạt điểm phù hợp tối thiểu 70/100."
	criteria = [
		{
			"code": "region",
			"label": "Khu vực",
			"result": "matched" if student.get("province") else "missing_data",
			"detail": "Đã xác định khu vực canonical." if student.get("province") else "Chưa tìm thấy khu vực canonical.",
		}
	]
	if item["status"] != "missing_data":
		criteria.append(
			{
				"code": "capacity",
				"label": "Khả năng tiếp nhận",
				"result": "matched" if any(candidate["eligible"] for candidate in candidates) else "no_match",
				"detail": "Có nhân sự còn khả năng tiếp nhận." if any(candidate["eligible"] for candidate in candidates) else "Chưa có nhân sự đạt điều kiện.",
			}
		)
	return {
		"item": item,
		"issue": _assignment_issue(item),
		"candidates": candidates,
		"explainability": {
			"policyVersion": ASSIGNMENT_POLICY_VERSION,
			"matchScore": item.get("matchScore"),
			"reasons": [explainability_reason],
			"criteria": criteria,
		},
		"events": _assignment_detail_events(metadata, student_id, lookups.get("owners", {})),
		"permissions": {
			"canResolve": item["status"] != "assigned",
			"canReassign": False,
		},
	}


@frappe.whitelist(methods=["GET"])
def get_lead_assignment_detail(**kwargs: Any) -> dict[str, Any]:
	"""Canonical Lead-named alias for the assignment detail contract."""
	return get_student_assignment_detail(**kwargs)


def _assignment_required_payload_text(value: Any, field: str, *, minimum: int = 1, maximum: int = 500) -> str:
	if not isinstance(value, str):
		raise_api_error("INVALID_PAYLOAD", f"{field} là bắt buộc.", frappe.ValidationError, 400)
	value = value.strip()
	if not minimum <= len(value) <= maximum:
		raise_api_error("INVALID_PAYLOAD", f"{field} không hợp lệ.", frappe.ValidationError, 400)
	return value


def _assignment_expected_revision(value: Any) -> int:
	if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value or "").strip()):
		raise_api_error("INVALID_PAYLOAD", "expectedRevision không hợp lệ.", frappe.ValidationError, 400)
	return int(value)


def _assignment_idempotency_key(value: Any) -> str:
	header_key = frappe.get_request_header("Idempotency-Key")
	key = str(header_key or "").strip()
	if value not in (None, "") and str(value).strip() != key:
		raise_api_error("INVALID_PAYLOAD", "Idempotency-Key phải được truyền qua header.", frappe.ValidationError, 400)
	if not 8 <= len(key) <= 140 or not re.fullmatch(r"[A-Za-z0-9._:-]+", key):
		raise_api_error("INVALID_PAYLOAD", "Idempotency-Key không hợp lệ.", frappe.ValidationError, 400)
	return key


def _assignment_region_name(value: str) -> str:
	filters = [{"name": value}, {"province_name": value}, {"province_code": value}]
	matches: set[str] = set()
	for candidate in filters:
		rows = _get_list(
			"CRM Province",
			filters=candidate,
			fields=["name"],
			limit_page_length=2,
			warnings=None,
		)
		matches.update(str(row.get("name")) for row in rows if row.get("name"))
	if len(matches) != 1:
		raise_api_error("INVALID_ASSIGNMENT", "Region không phải địa bàn hợp lệ.", frappe.ValidationError, 422)
	return next(iter(matches))


def _assignment_owner_team(owner_id: str, scope: dict[str, Any]) -> str | None:
	rows = [
		row
		for row in scope.get("memberships") or []
		if str(row.get("staff") or "") == owner_id and row.get("function") in ASSIGNMENT_OWNER_FUNCTIONS
	]
	team_ids = {str(row.get("team")) for row in rows if row.get("team")}
	return sorted(team_ids)[0] if len(team_ids) == 1 else None


def _assignment_receipt_exists(actor: str, idempotency_key: str) -> bool:
	try:
		from crm.fcrm.student_ownership import ownership_command_keys

		keys = ownership_command_keys(actor, idempotency_key)
		return bool(
			frappe.db.exists(
				"CRM Student Command Receipt", {"command_key": ["in", keys]}
			)
		)
	except Exception:
		return False


def _assignment_command_result(result: dict[str, Any], student_id: str, owner_id: str, reason: str) -> dict[str, Any]:
	event_name = result.get("event")
	event_id = str(event_name or "")
	applied_at = str(result.get("applied_at") or "")
	if event_name and frappe.db.exists("CRM Student Ownership Event", event_name):
		event = frappe.db.get_value(
			"CRM Student Ownership Event", event_name, ["event_id", "event_at", "reason"], as_dict=True
		)
		if event:
			event_id = str(event.get("event_id") or event_id)
			applied_at = str(event.get("event_at") or applied_at)
			reason = str(event.get("reason") or reason)
	if not applied_at:
		applied_at = _now(ZoneInfo(DEFAULT_TIMEZONE)).isoformat(timespec="seconds")
	owner_name = frappe.db.get_value("CRM Staff", owner_id, "full_name") or owner_id
	return {
		"studentId": student_id,
		"command": "resolve",
		"assignment": {
			"owner": {"id": owner_id, "displayName": str(owner_name)},
			"status": "assigned",
			"method": "manual",
			"reason": reason,
			"appliedAt": applied_at,
		},
		"revision": _assignment_revision({"ownership_revision": result.get("revision")}),
		"audit": {
			"eventId": event_id,
			"actorId": str(frappe.session.user),
			"occurredAt": applied_at,
		},
	}


@frappe.whitelist(methods=["POST"])
def resolve_student_assignment(
	studentId: str | None = None,
	ownerId: str | None = None,
	region: str | None = None,
	reason: str | None = None,
	expectedRevision: str | int | None = None,
	idempotency_key: str | None = None,
) -> dict[str, Any]:
	"""Resolve one unassigned Lead through the canonical ownership command."""
	access = _require_assignment_access()
	student_id = _assignment_required_payload_text(studentId, "studentId", maximum=140)
	owner_id = _assignment_required_payload_text(ownerId, "ownerId", maximum=140)
	manual_reason = _assignment_required_payload_text(reason, "reason", minimum=10, maximum=500)
	expected_revision = _assignment_expected_revision(expectedRevision)
	idempotency_key = _assignment_idempotency_key(idempotency_key)
	region_value = str(region or "").strip()
	if len(region_value) > 140:
		raise_api_error("INVALID_PAYLOAD", "region không hợp lệ.", frappe.ValidationError, 400)
	warnings: list[str] = []
	scope = _assignment_scope(access["user"], warnings)
	student = _assignment_find_student(student_id, None, scope, warnings)
	current_revision = _assignment_revision(student)
	# A retry must reach the ownership receipt before the already-assigned guard;
	# the canonical command then either replays the original result or rejects a
	# reused key with a different fingerprint.
	team_id = _assignment_owner_team(owner_id, scope)
	if not team_id:
		raise_api_error("ASSIGNMENT_OWNER_NOT_FOUND", "ownerId không thuộc team Sale hiện tại.", frappe.DoesNotExistError, 404)
	if student.get("owner_staff") or student.get("assigned_to"):
		if _assignment_receipt_exists(access["user"], idempotency_key):
			from crm.fcrm.student_ownership import change_student_ownership

			try:
				result = change_student_ownership(
					student=student_id,
					target_kind="owner",
					target_id=owner_id,
					target_team_id=team_id,
					reason=manual_reason,
					idempotency_key=idempotency_key,
					expected_revision=expected_revision,
					correlation_id=f"student-assignment:{idempotency_key}",
				)
			except Exception as exc:
				_code = getattr(exc, "code", None)
				if _code == "IDEMPOTENCY_KEY_REUSED":
					raise_api_error(_code, str(exc), frappe.ValidationError, 409)
				raise
			return _assignment_command_result(result, student_id, owner_id, manual_reason)
		raise_api_error("ALREADY_ASSIGNED", "Hồ sơ đã có người phụ trách; không thể ghi đè.", frappe.ValidationError, 409)
	if current_revision != expected_revision:
		raise_api_error("STALE_REVISION", "Hồ sơ đã được cập nhật bởi người dùng khác. Vui lòng tải lại.", frappe.ValidationError, 409)
	if not region_value and not student.get("province"):
		raise_api_error("INVALID_ASSIGNMENT", "Khu vực là bắt buộc với Lead đang thiếu khu vực.", frappe.ValidationError, 422)
	if region_value:
		province = _assignment_region_name(region_value)
	if region_value and not student.get("province"):
		# Keep the region update in the same transaction as the ownership command.
		# CRM Lead's save hook records the material context revision while the
		# ownership command remains the only writer of owner fields.
		locked = frappe.get_doc("CRM Lead", student_id)
		locked.province = province
		locked.save(ignore_permissions=True)
	from crm.fcrm.student_ownership import StudentOwnershipError, change_student_ownership
	try:
		result = change_student_ownership(
			student=student_id,
			target_kind="owner",
			target_id=owner_id,
			target_team_id=team_id,
			reason=manual_reason,
			idempotency_key=idempotency_key,
			expected_revision=expected_revision,
			correlation_id=f"student-assignment:{idempotency_key}",
		)
	except StudentOwnershipError as exc:
		if exc.code in {"UNAUTHORIZED", "OUT_OF_SCOPE"}:
			raise_api_error("FORBIDDEN", str(exc), frappe.PermissionError, 403)
		if exc.code in {"STALE_OWNERSHIP_REVISION", "STALE_REVISION"}:
			raise_api_error("STALE_REVISION", str(exc), frappe.ValidationError, 409)
		if exc.code == "IDEMPOTENCY_KEY_REUSED":
			raise_api_error(exc.code, str(exc), frappe.ValidationError, 409)
		if exc.code == "INVALID_TARGET":
			raise_api_error("ASSIGNMENT_OWNER_NOT_FOUND", str(exc), frappe.DoesNotExistError, 404)
		raise_api_error("INVALID_ASSIGNMENT", str(exc), frappe.ValidationError, 422)
	return _assignment_command_result(result, student_id, owner_id, manual_reason)


@frappe.whitelist(methods=["POST"])
def resolve_lead_assignment(**kwargs: Any) -> dict[str, Any]:
	"""Canonical Lead-named alias for the ownership command adapter."""
	return resolve_student_assignment(**kwargs)


@frappe.whitelist(methods=["GET"])
def get_sales_team_workspace(
	admissionYear: str | int | None = None,
	date: str | None = None,
	timezone: str = DEFAULT_TIMEZONE,
	availability: str = "all",
	q: str = "",
	page: str | int = 1,
	pageSize: str | int = 50,
	sort: str = "support",
	order: str | None = None,
) -> dict[str, Any]:
	"""Return the current Lead Sale team's member workspace projection."""
	from crm.api.lead_sales_team import get_sales_team_workspace as implementation

	return implementation(admissionYear, date, timezone, availability, q, page, pageSize, sort, order)


@frappe.whitelist(methods=["GET"])
def get_sales_team_member_detail(
	memberId: str,
	admissionYear: str | int | None = None,
	date: str | None = None,
	timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
	"""Return a re-scoped aggregate detail for one Lead Sale member."""
	from crm.api.lead_sales_team import get_sales_team_member_detail as implementation

	return implementation(memberId, admissionYear, date, timezone)
