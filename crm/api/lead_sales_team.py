"""Read-only, session-scoped projections for the Lead Sales team dashboard."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from functools import cmp_to_key
from typing import Any
from zoneinfo import ZoneInfo

import frappe

from crm.api import lead_sale as lead_sale_api
from crm.api import sale as sale_overview
from crm.api.director_school_common import parse_limit, raise_api_error

DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"
MEMBER_FUNCTIONS = frozenset({"Sale", "CTV-Sale"})
AVAILABILITY_VALUES = frozenset({"all", "active", "away", "leave"})
SORT_VALUES = frozenset({"support", "load", "name"})
ORDER_VALUES = frozenset({"asc", "desc"})

TEAM_MEMBER_FIELDS = ["name", "full_name", "user", "is_active"]
STUDENT_FIELDS = [
	"name",
	"student_name",
	"lifecycle_stage",
	"enrollment_status",
	"admission_year",
	"owner_staff",
	"assigned_to",
	"owning_team",
	"province",
	"major",
	"creation",
	"enrollment_date",
]
CAPACITY_FIELDS = [
	"name",
	"staff",
	"team",
	"period_start",
	"period_end",
	"max_active_students",
	"capacity_units",
	"approved",
	"effective_from",
	"effective_until",
	"modified",
]


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
	"""Return one consistent snapshot for the authenticated Lead Sales team."""
	access = lead_sale_api._require_access()
	report_timezone = lead_sale_api._parse_timezone(timezone)
	report_date = lead_sale_api._parse_report_date(date, report_timezone)
	year = _resolve_admission_year(admissionYear)
	query = _parse_query(availability, q, page, pageSize, sort, order)
	as_of = lead_sale_api._now(report_timezone)
	snapshot = _build_snapshot(access, year, report_date, report_timezone, as_of)

	filtered_members = [
		member
		for member in snapshot["members"]
		if (query["availability"] == "all" or member["availability"] == query["availability"])
		and _matches(member, query["q"])
	]
	filtered_members = _sort_members(filtered_members, query["sort"], query["order"])
	total = len(filtered_members)
	start = (query["page"] - 1) * query["page_size"]
	page_members = filtered_members[start : start + query["page_size"]]
	total_pages = _total_pages(total, query["page_size"])

	response = _public_snapshot(snapshot)
	response["members"] = page_members
	response["pagination"] = {
		"page": query["page"],
		"pageSize": query["page_size"],
		"total": total,
		"totalPages": total_pages,
		"hasNextPage": query["page"] < total_pages,
	}
	return response


def get_sales_team_member_detail(
	memberId: str,
	admissionYear: str | int | None = None,
	date: str | None = None,
	timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
	"""Return aggregate detail for one member after rechecking team scope."""
	access = lead_sale_api._require_access()
	member_id = str(memberId or "").strip()
	if not member_id or len(member_id) > 140:
		raise_api_error("INVALID_QUERY", "Tham số memberId là bắt buộc.", frappe.ValidationError, 400)
	report_timezone = lead_sale_api._parse_timezone(timezone)
	report_date = lead_sale_api._parse_report_date(date, report_timezone)
	year = _resolve_admission_year(admissionYear)
	as_of = lead_sale_api._now(report_timezone)
	snapshot = _build_snapshot(access, year, report_date, report_timezone, as_of)
	member = next((item for item in snapshot["members"] if item["id"] == member_id), None)
	if member is None:
		raise_api_error(
			"TEAM_MEMBER_NOT_FOUND",
			"Không tìm thấy thành viên trong đội Sale hiện tại.",
			frappe.DoesNotExistError,
			404,
		)

	return {
		"meta": {
			"admissionYear": _year_number(year),
			"date": report_date.isoformat(),
			"asOf": as_of.isoformat(timespec="seconds"),
			"timezone": getattr(report_timezone, "key", str(report_timezone)),
		},
		"member": member,
		"healthAssessment": _health_assessment(member, as_of),
		"metricWindow": _metric_window(_year_number(year), report_date, report_timezone),
		"permissions": {"canViewStudents": True},
	}


def _build_snapshot(
	access: dict[str, str],
	year: str,
	report_date: date,
	report_timezone: ZoneInfo,
	as_of: datetime,
) -> dict[str, Any]:
	warnings: list[str] = []
	scope = _team_scope(access["user"], report_date, warnings)
	students = _load_students(scope, year, warnings)
	student_ids = [str(row.get("name")) for row in students if row.get("name")]
	contacts = sale_overview._load_contacts(student_ids, warnings)
	applications = sale_overview._load_applications(student_ids, year, warnings)
	interactions = sale_overview._load_interactions(student_ids, warnings)
	tasks = sale_overview._load_tasks(student_ids, warnings)
	records = lead_sale_api._build_records(students, contacts, applications, interactions)
	annotated_tasks = lead_sale_api._annotate_tasks(tasks, as_of, report_timezone)
	capacities = _load_capacities(scope, report_date, warnings)
	labels = _load_labels(students, warnings)
	members = _build_members(
		scope["members"],
		students,
		records,
		interactions,
		annotated_tasks,
		capacities,
		labels,
		report_date,
		report_timezone,
	)

	if not members:
		raise_api_error(
			"TEAM_MEMBER_NOT_FOUND",
			"Đội Sale hiện tại chưa có thành viên Sale hoạt động.",
			frappe.DoesNotExistError,
			404,
		)

	assigned_students = sum(member["activeStudents"] for member in members)
	total_capacity = sum(member["capacity"] for member in members)
	support_members = [member for member in members if member["health"] == "support"]
	return {
		"meta": {
			"viewer": lead_sale_api._viewer(access["user"]),
			"team": lead_sale_api._team_meta(scope["teams"]),
			"admissionYear": _year_number(year),
			"date": report_date.isoformat(),
			"asOf": as_of.isoformat(timespec="seconds"),
			"timezone": getattr(report_timezone, "key", str(report_timezone)),
			"status": "partial" if warnings else "available",
			"warnings": sorted(set(warnings)),
		},
		"summary": {
			"memberCount": len(members),
			"activeMemberCount": sum(member["availability"] == "active" for member in members),
			"assignedStudents": assigned_students,
			"totalCapacity": total_capacity,
			"loadRate": _rate(assigned_students, total_capacity),
			"supportMemberCount": len(support_members),
			"overdueStudents": sum(member["overdue"] for member in members),
		},
		"attention": {
			"count": len(support_members),
			"items": [
				{
					"memberId": member["id"],
					"displayName": member["displayName"],
					"availability": member["availability"],
					"health": "support",
					"activeStudents": member["activeStudents"],
					"capacity": member["capacity"],
					"loadRate": member["loadRate"],
					"overdue": member["overdue"],
					"supportReason": member["supportReason"] or "Cần theo dõi thêm.",
				}
				for member in _sort_members(support_members, "support", "desc")
			],
		},
		"loadSummary": {
			"assignedStudents": assigned_students,
			"totalCapacity": total_capacity,
			"loadRate": _rate(assigned_students, total_capacity),
			"topMembers": [
				{
					"memberId": member["id"],
					"displayName": member["displayName"],
					"activeStudents": member["activeStudents"],
					"capacity": member["capacity"],
					"loadRate": member["loadRate"],
					"health": member["health"],
				}
				for member in _sort_members(members, "load", "desc")[:4]
			],
		},
		"members": members,
	}


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
	return {
		"meta": snapshot["meta"],
		"summary": snapshot["summary"],
		"attention": snapshot["attention"],
		"loadSummary": snapshot["loadSummary"],
		"members": snapshot["members"],
	}


def _team_scope(user: str, report_date: date, warnings: list[str]) -> dict[str, Any]:
	lead_rows = _read_list(
		"CRM Staff",
		filters={"user": user, "is_active": 1},
		fields=["name", "full_name", "user"],
		warnings=warnings,
		warning_key="team",
	)
	if not lead_rows:
		raise_api_error(
			"TEAM_NOT_FOUND",
			"Không tìm thấy đội Sale của người dùng hiện tại.",
			frappe.DoesNotExistError,
			404,
		)

	lead_staff = str(lead_rows[0].get("name") or "")
	lead_memberships = _read_all(
		"CRM Team Membership",
		filters={"parent": lead_staff, "parenttype": "CRM Staff"},
		fields=["team", "function", "is_primary", "effective_from", "effective_until"],
		warnings=warnings,
		warning_key="team",
	)
	team_ids = sorted(
		{
			str(row.get("team"))
			for row in lead_memberships
			if row.get("team") and _date_active(row, report_date)
		}
	)
	if not team_ids:
		raise_api_error(
			"TEAM_NOT_FOUND", "Người dùng hiện tại chưa thuộc đội Sale nào.", frappe.DoesNotExistError, 404
		)

	teams = _read_list(
		"CRM Team",
		filters={"name": ["in", team_ids], "team_type": "Sales", "is_active": 1},
		fields=["name", "team_name", "campus", "is_active"],
		warnings=warnings,
		warning_key="team",
	)
	teams = [team for team in teams if str(team.get("name") or "") in team_ids]
	if not teams:
		raise_api_error(
			"TEAM_NOT_FOUND", "Đội Sale hiện tại không còn khả dụng.", frappe.DoesNotExistError, 404
		)
	team_ids = sorted({str(team["name"]) for team in teams})

	membership_rows = _read_all(
		"CRM Team Membership",
		filters={"team": ["in", team_ids], "parenttype": "CRM Staff"},
		fields=["parent as staff", "team", "function", "effective_from", "effective_until"],
		warnings=warnings,
		warning_key="team",
	)
	membership_rows = [
		row
		for row in membership_rows
		if row.get("staff") and row.get("function") in MEMBER_FUNCTIONS and _date_active(row, report_date)
	]
	staff_ids = sorted({str(row["staff"]) for row in membership_rows})
	if not staff_ids:
		raise_api_error(
			"TEAM_NOT_FOUND", "Đội Sale hiện tại chưa có thành viên hoạt động.", frappe.DoesNotExistError, 404
		)

	staff_fields = list(TEAM_MEMBER_FIELDS)
	if _has_doctype_field("CRM Staff", "availability"):
		staff_fields.append("availability")
	staff_rows = _read_list(
		"CRM Staff",
		filters={"name": ["in", staff_ids], "is_active": 1},
		fields=staff_fields,
		warnings=warnings,
		warning_key="team",
	)
	user_ids = {str(row.get("user")) for row in staff_rows if row.get("user")}
	user_rows = _read_list(
		"User",
		filters={"name": ["in", sorted(user_ids)]},
		fields=["name", "full_name", "email", "enabled"],
		warnings=warnings,
		warning_key="team",
	)
	users = {str(row.get("name")): row for row in user_rows if row.get("name")}
	memberships_by_staff: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in membership_rows:
		memberships_by_staff[str(row["staff"])].append(dict(row))

	members = []
	for staff in staff_rows:
		staff_id = str(staff.get("name") or "")
		user_id = str(staff.get("user") or "")
		user = users.get(user_id, {})
		if not staff_id or not user_id or user.get("enabled") in (0, False, "0"):
			continue
		members.append(
			{
				"id": staff_id,
				"displayName": str(staff.get("full_name") or user.get("full_name") or user_id),
				"email": str(user.get("email") or ""),
				"availability": _availability(staff.get("availability")),
				"teams": {str(row.get("team")) for row in memberships_by_staff[staff_id] if row.get("team")},
			}
		)
	if not members:
		raise_api_error(
			"TEAM_NOT_FOUND", "Đội Sale hiện tại chưa có thành viên hoạt động.", frappe.DoesNotExistError, 404
		)

	return {
		"teams": teams,
		"team_ids": team_ids,
		"members": sorted(members, key=lambda row: (_fold(row["displayName"]), row["id"])),
		"staff_ids": [member["id"] for member in members],
	}


def _load_students(scope: dict[str, Any], year: str, warnings: list[str]) -> list[dict[str, Any]]:
	if not _table_exists("CRM Student"):
		raise_api_error(
			"SALES_TEAM_UNAVAILABLE",
			"Không thể đọc dữ liệu học sinh của đội Sale.",
			frappe.ValidationError,
			503,
		)
	team_ids = scope["team_ids"]
	staff_ids = scope["staff_ids"]
	try:
		return [
			dict(row)
			for row in frappe.get_list(
				"CRM Student",
				filters={"admission_year": year, "lifecycle_stage": ["!=", "Lost"]},
				or_filters=[
					["owner_staff", "in", staff_ids],
					["owning_team", "in", team_ids],
				],
				fields=STUDENT_FIELDS,
				order_by="name asc",
				limit_page_length=0,
			)
		]
	except Exception:
		warnings.append("students.source_unavailable")
		raise_api_error(
			"SALES_TEAM_UNAVAILABLE",
			"Không thể đọc dữ liệu học sinh của đội Sale.",
			frappe.ValidationError,
			503,
		)


def _load_capacities(scope: dict[str, Any], report_date: date, warnings: list[str]) -> dict[str, int]:
	rows = _read_list(
		"CRM Staff Capacity Period",
		filters={"staff": ["in", scope["staff_ids"]], "approved": 1},
		fields=CAPACITY_FIELDS,
		warnings=warnings,
		warning_key="capacity",
	)
	selected: dict[str, dict[str, Any]] = {}
	for row in rows:
		staff_id = str(row.get("staff") or "")
		if not staff_id or not _date_active(row, report_date):
			continue
		member = next((item for item in scope["members"] if item["id"] == staff_id), None)
		if not member:
			continue
		team_id = str(row.get("team") or "")
		if team_id and team_id not in member["teams"]:
			continue
		previous = selected.get(staff_id)
		if previous and _capacity_sort_key(previous, member) >= _capacity_sort_key(row, member):
			continue
		selected[staff_id] = dict(row)

	result: dict[str, int] = {}
	for member in scope["members"]:
		row = selected.get(member["id"])
		if not row:
			result[member["id"]] = 0
			continue
		value = row.get("max_active_students")
		if value is None or value == "":
			value = row.get("capacity_units")
		result[member["id"]] = _count(value)
	return result


def _build_members(
	scope_members: list[dict[str, Any]],
	students: list[dict[str, Any]],
	records: list[dict[str, Any]],
	interactions: list[dict[str, Any]],
	tasks: list[dict[str, Any]],
	capacities: dict[str, int],
	labels: dict[str, dict[str, str]],
	report_date: date,
	report_timezone: ZoneInfo,
) -> list[dict[str, Any]]:
	student_by_id = {str(row.get("name")): row for row in students if row.get("name")}
	records_by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for record in records:
		owner = str(record.get("owner_staff") or "")
		if owner:
			records_by_owner[owner].append(record)
	interactions_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for interaction in interactions:
		if interaction.get("student"):
			interactions_by_student[str(interaction["student"])].append(interaction)

	month_start = report_date.replace(day=1)
	month_end = lead_sale_api._add_months(month_start, 1) - timedelta(days=1)
	result = []
	for base in scope_members:
		owned_records = records_by_owner.get(base["id"], [])
		owned_ids = {str(record["id"]) for record in owned_records}
		overdue_ids = {
			str(task.get("student_id"))
			for task in tasks
			if task.get("student_id") in owned_ids
			and task.get("is_overdue")
			and not lead_sale_api._task_is_terminal(task)
		}
		active_students = len(owned_records)
		admitted_this_month = sum(
			1
			for record in owned_records
			if sale_overview._date_inclusive(
				record.get("admitted_at"), month_start, month_end, report_timezone
			)
		)
		consulted_today = sum(
			1
			for record in owned_records
			if sale_overview._date_inclusive(
				record.get("consulted_at"), report_date, report_date, report_timezone
			)
		)
		capacity = capacities.get(base["id"], 0)
		load_rate = _rate(active_students, capacity)
		health = "support" if overdue_ids or (load_rate is not None and load_rate >= 80) else "good"
		support_reason = _support_reason(len(overdue_ids), load_rate)
		last_activity = max(
			(
				sale_overview._as_timezone(
					sale_overview._coerce_datetime(interaction.get("interaction_datetime")), report_timezone
				)
				for student_id in owned_ids
				for interaction in interactions_by_student.get(student_id, [])
				if interaction.get("interaction_datetime")
			),
			default=None,
		)
		regions = {
			labels["provinces"].get(str(student_by_id[record["id"]].get("province")))
			or str(student_by_id[record["id"]].get("province") or "")
			for record in owned_records
			if student_by_id.get(record["id"], {}).get("province")
		}
		specialties = {
			labels["majors"].get(str(student_by_id[record["id"]].get("major")))
			or str(student_by_id[record["id"]].get("major") or "")
			for record in owned_records
			if student_by_id.get(record["id"], {}).get("major")
		}
		result.append(
			{
				"id": base["id"],
				"displayName": base["displayName"],
				"email": base["email"],
				"availability": base["availability"],
				"health": health,
				"activeStudents": active_students,
				"capacity": capacity,
				"loadRate": load_rate,
				"consultedToday": consulted_today,
				"admittedThisMonth": admitted_this_month,
				"overdue": len(overdue_ids),
				"conversionRate": _rate(admitted_this_month, active_students),
				"regions": sorted({value for value in regions if value}, key=_fold),
				"specialties": sorted({value for value in specialties if value}, key=_fold),
				"lastActivityAt": last_activity.isoformat(timespec="seconds") if last_activity else None,
				"supportReason": support_reason,
			}
		)
	return result


def _load_labels(students: list[dict[str, Any]], warnings: list[str]) -> dict[str, dict[str, str]]:
	return {
		"provinces": _lookup_labels(
			"CRM Province", {row.get("province") for row in students}, "province_name", warnings
		),
		"majors": _lookup_labels("CRM Major", {row.get("major") for row in students}, "major_name", warnings),
	}


def _lookup_labels(doctype: str, values: set[Any], label_field: str, warnings: list[str]) -> dict[str, str]:
	keys = sorted({str(value) for value in values if value})
	if not keys:
		return {}
	rows = _read_list(
		doctype,
		filters={"name": ["in", keys]},
		fields=["name", label_field],
		warnings=warnings,
		warning_key=f"lookup.{doctype.lower().replace(' ', '_')}",
	)
	return {
		str(row.get("name")): str(row.get(label_field) or row.get("name")) for row in rows if row.get("name")
	}


def _parse_query(
	availability: str,
	q: str,
	page: str | int,
	page_size: str | int,
	sort: str,
	order: str | None,
) -> dict[str, Any]:
	availability_value = str(availability or "all").strip().lower()
	if availability_value not in AVAILABILITY_VALUES:
		raise_api_error("INVALID_QUERY", "Tham số availability không hợp lệ.", frappe.ValidationError, 400)
	search = str(q or "").strip()
	if len(search) > 140:
		raise_api_error("INVALID_QUERY", "Tham số q không hợp lệ.", frappe.ValidationError, 400)
	page_value = _positive_int(page, "page", 1)
	page_length = parse_limit(page_size, field="pageSize", minimum=1, maximum=100, default=50)
	sort_value = str(sort or "support").strip().lower()
	if sort_value not in SORT_VALUES:
		raise_api_error("INVALID_QUERY", "Tham số sort không hợp lệ.", frappe.ValidationError, 400)
	order_value = (
		str(order).strip().lower() if order not in (None, "") else ("asc" if sort_value == "name" else "desc")
	)
	if order_value not in ORDER_VALUES:
		raise_api_error("INVALID_QUERY", "Tham số order không hợp lệ.", frappe.ValidationError, 400)
	return {
		"availability": availability_value,
		"q": search,
		"page": page_value,
		"page_size": page_length,
		"sort": sort_value,
		"order": order_value,
	}


def _resolve_admission_year(value: Any) -> str:
	if value not in (None, ""):
		text = str(value).strip()
		if not re.fullmatch(r"\d{4}", text) or not 2000 <= int(text) <= 2100:
			raise_api_error(
				"INVALID_QUERY", "Tham số admissionYear không hợp lệ.", frappe.ValidationError, 400
			)
		rows = _read_list(
			"CRM Admission Year",
			filters={"name": text},
			fields=["name", "year_name"],
			warnings=None,
		)
		if not rows:
			rows = _read_list(
				"CRM Admission Year",
				filters={"year_name": text},
				fields=["name", "year_name"],
				warnings=None,
			)
		if rows:
			return str(rows[0].get("name") or rows[0].get("year_name") or text)
		raise_api_error(
			"ADMISSION_YEAR_NOT_FOUND", "Không tìm thấy kỳ tuyển sinh.", frappe.ValidationError, 422
		)

	rows = _read_list(
		"CRM Admission Year",
		filters={"is_active": 1},
		fields=["name", "year_name"],
		warnings=None,
		order_by="year_name desc, name desc",
	)
	if rows:
		return str(rows[0].get("name") or rows[0].get("year_name"))
	current_year = str(lead_sale_api._now(ZoneInfo(DEFAULT_TIMEZONE)).year)
	rows = _read_list(
		"CRM Admission Year",
		filters={"name": current_year},
		fields=["name", "year_name"],
		warnings=None,
	)
	if rows:
		return current_year
	raise_api_error(
		"ADMISSION_YEAR_NOT_FOUND", "Không tìm thấy kỳ tuyển sinh hiện hành.", frappe.ValidationError, 422
	)


def _health_assessment(member: dict[str, Any], as_of: datetime) -> dict[str, Any]:
	reasons = []
	if member["overdue"]:
		reasons.append(
			{
				"code": "OVERDUE_CONTACTS",
				"label": "Hồ sơ quá hạn liên hệ",
				"value": member["overdue"],
				"detail": f"Có {member['overdue']} hồ sơ chưa được liên hệ đúng hạn.",
			}
		)
	if member["loadRate"] is not None and member["loadRate"] >= 80:
		reasons.append(
			{
				"code": "CAPACITY_NEAR_LIMIT",
				"label": "Tải phụ trách cao",
				"value": member["loadRate"],
				"detail": f"Đang sử dụng {member['loadRate']}% khả năng tiếp nhận.",
			}
		)
	return {
		"status": member["health"],
		"evaluatedAt": as_of.isoformat(timespec="seconds"),
		"reasons": reasons,
	}


def _metric_window(year: int, report_date: date, timezone: ZoneInfo) -> dict[str, Any]:
	month_start = report_date.replace(day=1)
	month_end = lead_sale_api._add_months(month_start, 1) - timedelta(days=1)
	return {
		"admissionYear": year,
		"today": _date_window(report_date, timezone),
		"month": _date_window(month_start, timezone, month_end),
	}


def _date_window(start: date, timezone: ZoneInfo, end: date | None = None) -> dict[str, str]:
	end = end or start
	return {
		"from": datetime.combine(start, time.min, tzinfo=timezone).isoformat(timespec="seconds"),
		"to": datetime.combine(end, time(23, 59, 59), tzinfo=timezone).isoformat(timespec="seconds"),
	}


def _sort_members(members: list[dict[str, Any]], sort: str, order: str) -> list[dict[str, Any]]:
	def compare(left: dict[str, Any], right: dict[str, Any]) -> int:
		if sort == "support":
			left_health = left["health"] == "support"
			right_health = right["health"] == "support"
			if left_health != right_health:
				return -1 if left_health else 1
			for field in ("overdue", "loadRate"):
				comparison = _compare_metric(left.get(field), right.get(field), order)
				if comparison:
					return comparison
		elif sort == "load":
			for field in ("loadRate", "activeStudents"):
				comparison = _compare_metric(left.get(field), right.get(field), order)
				if comparison:
					return comparison
		else:
			comparison = _compare_metric(_fold(left["displayName"]), _fold(right["displayName"]), order)
			if comparison:
				return comparison
		return _compare_metric(str(left["id"]), str(right["id"]), "asc")

	return sorted(members, key=cmp_to_key(compare))


def _compare_metric(left: Any, right: Any, order: str) -> int:
	if left is None and right is not None:
		return 1
	if left is not None and right is None:
		return -1
	if left == right:
		return 0
	if order == "desc":
		return -1 if left > right else 1
	return -1 if left < right else 1


def _matches(member: dict[str, Any], query: str) -> bool:
	if not query:
		return True
	needle = _fold(query)
	return needle in _fold(" ".join(str(member.get(field) or "") for field in ("id", "displayName", "email")))


def _support_reason(overdue: int, load_rate: float | None) -> str | None:
	if overdue and load_rate is not None and load_rate >= 80:
		return f"Đang gần chạm mức tiếp nhận và còn {overdue} hồ sơ quá hạn"
	if overdue:
		return f"{overdue} hồ sơ chưa được liên hệ đúng hạn"
	if load_rate is not None and load_rate >= 80:
		return "Đang gần chạm mức tiếp nhận"
	return None


def _capacity_sort_key(row: dict[str, Any], member: dict[str, Any]) -> tuple[Any, ...]:
	team_match = bool(row.get("team") and str(row.get("team")) in member["teams"])
	return (
		int(team_match),
		_date_value(row.get("period_start")) or date.min,
		_date_value(row.get("effective_from")) or date.min,
		str(row.get("modified") or ""),
		str(row.get("name") or ""),
	)


def _date_active(row: dict[str, Any], target: date) -> bool:
	start = _date_value(row.get("effective_from") or row.get("period_start"))
	end = _date_value(row.get("effective_until") or row.get("period_end"))
	return (start is None or start <= target) and (end is None or end >= target)


def _date_value(value: Any) -> date | None:
	if not value:
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	try:
		return frappe.utils.getdate(value)
	except (AttributeError, TypeError, ValueError):
		try:
			return datetime.strptime(str(value), "%Y-%m-%d").date()
		except (TypeError, ValueError):
			return None


def _positive_int(value: Any, field: str, default: int) -> int:
	if value in (None, ""):
		return default
	if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value).strip()):
		raise_api_error("INVALID_QUERY", f"Tham số {field} không hợp lệ.", frappe.ValidationError, 400)
	parsed = int(value)
	if parsed < 1:
		raise_api_error("INVALID_QUERY", f"Tham số {field} không hợp lệ.", frappe.ValidationError, 400)
	return parsed


def _count(value: Any) -> int:
	try:
		return max(0, int(value or 0))
	except (TypeError, ValueError):
		return 0


def _rate(numerator: int, denominator: int) -> float | None:
	if denominator <= 0:
		return None
	return round(min(100, max(0, numerator / denominator * 100)), 1)


def _year_number(value: Any) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return 0


def _availability(value: Any) -> str:
	value = str(value or "active").strip().lower()
	return value if value in {"active", "away", "leave"} else "active"


def _fold(value: Any) -> str:
	return lead_sale_api._assignment_fold(value)


def _total_pages(total: int, page_size: int) -> int:
	return max(1, (total + page_size - 1) // page_size)


def _read_list(
	doctype: str,
	*,
	filters: dict[str, Any],
	fields: list[str],
	warnings: list[str] | None,
	warning_key: str | None = None,
	order_by: str | None = None,
) -> list[dict[str, Any]]:
	return [
		dict(row)
		for row in lead_sale_api._get_list(
			doctype,
			filters=filters,
			fields=fields,
			limit_page_length=0,
			warnings=warnings,
			warning_key=warning_key,
			order_by=order_by,
		)
	]


def _read_all(
	doctype: str,
	*,
	filters: dict[str, Any],
	fields: list[str],
	warnings: list[str] | None,
	warning_key: str | None = None,
	order_by: str | None = None,
) -> list[dict[str, Any]]:
	"""Read child-table projections that have no standalone DocType permissions."""
	try:
		if not frappe.db.table_exists(doctype):
			if warnings is not None and warning_key:
				warnings.append(f"{warning_key}.source_unavailable")
			return []
		kwargs: dict[str, Any] = {
			"filters": filters,
			"fields": fields,
			"limit_page_length": 0,
		}
		if order_by:
			kwargs["order_by"] = order_by
		return [dict(row) for row in frappe.get_all(doctype, **kwargs)]
	except Exception:
		if warnings is not None and warning_key:
			warnings.append(f"{warning_key}.source_unavailable")
		return []


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except (AttributeError, frappe.DoesNotExistError):
		return False


def _has_doctype_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).has_field(fieldname))
	except (AttributeError, frappe.DoesNotExistError, frappe.ValidationError):
		return False
