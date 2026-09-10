"""Aggregate regional admissions performance for the Director dashboard."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import frappe

from crm.api.director_school_common import raise_api_error, require_director_access, resolve_admission_year

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
TREND_MONTHS = 6
CAPABILITY_COLUMNS = (
	{"key": "leadGeneration", "label": "Tạo nguồn hồ sơ"},
	{"key": "counselling", "label": "Tư vấn"},
	{"key": "quality", "label": "Chất lượng hồ sơ"},
	{"key": "conversion", "label": "Tỷ lệ nhập học"},
	{"key": "campaigns", "label": "Hoạt động tuyển sinh"},
	{"key": "productivity", "label": "Năng suất đội ngũ"},
)
FUNNEL_STAGES = (
	("applications", "Hồ sơ đăng ký"),
	("qualified", "Đủ điều kiện"),
	("counselling", "Đang tư vấn"),
	("enrolled", "Đã nhập học"),
)
STUDENT_FIELDS = [
	"name",
	"admission_year",
	"province",
	"student_stage",
	"creation",
	"enrollment_date",
]


@frappe.whitelist(methods=["GET"])
def get_director_regional_performance(
	admissionYear: str | int | None = None, scope: str = "all"
) -> dict[str, Any]:
	"""Return one PII-free, internally consistent regional performance snapshot."""
	access = require_director_access()
	admission_year = resolve_admission_year(admissionYear)
	scope_context = _resolve_scope(scope, access)
	as_of = _now()
	warnings: list[str] = []
	students = _load_students(admission_year, scope_context, warnings)
	provinces = _build_provinces(students, admission_year, as_of, warnings)
	return {
		"meta": {
			"admissionYear": int(admission_year),
			"scope": scope_context["id"],
			"scopeLabel": scope_context["label"],
			"asOf": as_of.isoformat(timespec="seconds"),
			"timezone": "Asia/Ho_Chi_Minh",
			"status": "partial" if warnings else "available",
			"trendMonths": TREND_MONTHS,
			"warnings": list(dict.fromkeys(warnings)),
		},
		"capabilityColumns": list(CAPABILITY_COLUMNS),
		"provinces": provinces,
		"priorityActions": _build_priority_actions(provinces),
	}


def _resolve_scope(value: Any, access: dict[str, Any]) -> dict[str, str | None]:
	text = str(value or "all").strip()
	if not text or len(text) > 140 or any(ord(char) < 32 for char in text):
		raise_api_error("INVALID_QUERY", "Tham số scope không hợp lệ.", frappe.ValidationError, 400)
	if text.casefold() == "all":
		return {"id": "all", "label": "Toàn bộ địa bàn", "territory": None}
	rows = frappe.get_all(
		"CRM Territory", filters={"name": text}, fields=["name", "territory_name"], limit_page_length=1
	)
	if not rows:
		rows = frappe.get_all(
			"CRM Territory",
			filters={"territory_code": text},
			fields=["name", "territory_name"],
			limit_page_length=1,
		)
	if len(rows) != 1:
		raise_api_error(
			"INVALID_SCOPE", "Scope không tồn tại hoặc không hợp lệ.", frappe.ValidationError, 422
		)
	territory = dict(rows[0])
	if access["roleState"] not in {"platform_superuser", "system_manager"}:
		staff_territory = frappe.db.get_value(
			"CRM Staff", {"user": access["user"], "is_active": 1}, "territory"
		)
		if not staff_territory or staff_territory != territory["name"]:
			raise_api_error(
				"FORBIDDEN", "Scope không nằm trong phạm vi được cấp quyền.", frappe.PermissionError, 403
			)
	return {
		"id": territory["name"],
		"label": territory.get("territory_name") or territory["name"],
		"territory": territory["name"],
	}


def _load_students(admission_year: str, scope: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
	rows = [
		dict(row)
		for row in frappe.get_all(
			"CRM Student",
			filters={"admission_year": admission_year},
			fields=STUDENT_FIELDS,
			order_by="creation asc, name asc",
			limit_page_length=0,
		)
	]
	for row in rows:
		stage = str(row.get("student_stage") or "New").strip()
		row["processing_status"] = {
			"New": "new",
			"Attempting": "processing",
			"Qualified": "processed",
			"Connected": "created",
			"Disqualified": "invalid",
		}.get(stage, "new")
		row["resolution"] = "CREATED" if stage == "Connected" else None
	if not scope.get("territory"):
		return rows
	if not frappe.db.table_exists("CRM Territory Geography Assignment"):
		raise_api_error(
			"REGIONAL_PERFORMANCE_DATA_UNAVAILABLE",
			"Không thể xác định phạm vi địa lý.",
			frappe.ValidationError,
			503,
		)
	assignments = frappe.get_all(
		"CRM Territory Geography Assignment",
		filters={"territory": scope["territory"], "status": "Active", "geography_type": "Province"},
		fields=["geography"],
		limit_page_length=0,
	)
	province_ids = {row.get("geography") for row in assignments}
	if not province_ids:
		warnings.append("Territory chưa có tỉnh/thành đang hiệu lực.")
		return []
	return [row for row in rows if row.get("province") in province_ids]


def _build_provinces(
	students: list[dict[str, Any]], admission_year: str, as_of: datetime, warnings: list[str]
) -> list[dict[str, Any]]:
	province_ids = sorted({row.get("province") for row in students if row.get("province")})
	if not province_ids:
		return []
	province_rows = frappe.get_all(
		"CRM Province",
		filters={"name": ["in", province_ids]},
		fields=["name", "province_name", "province_code"],
		limit_page_length=0,
	)
	labels = {
		row["name"]: row.get("province_name") or row.get("province_code") or row["name"]
		for row in province_rows
	}
	targets = _load_targets(admission_year, province_ids, warnings)
	previous = _load_previous_students(admission_year, province_ids, warnings)
	workforce = _load_workforce(province_ids, warnings)
	grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in students:
		if row.get("province"):
			grouped[row["province"]].append(row)
	return [
		_build_province(
			province_id,
			labels.get(province_id, province_id),
			grouped[province_id],
			previous.get(province_id, []),
			targets.get(province_id),
			workforce.get(province_id),
			as_of,
		)
		for province_id in sorted(grouped, key=lambda item: labels.get(item, item))
	]


def _load_workforce(province_ids: list[str], warnings: list[str]) -> dict[str, dict[str, int]]:
	if not frappe.db.table_exists("CRM Territory Geography Assignment"):
		warnings.append("Chưa có nguồn phân công đội ngũ theo địa bàn.")
		return {}
	assignments = frappe.get_all(
		"CRM Territory Geography Assignment",
		filters={"geography_type": "Province", "geography": ["in", province_ids], "status": "Active"},
		fields=["territory", "geography"],
		limit_page_length=0,
	)
	territory_to_province = {row.get("territory"): row.get("geography") for row in assignments}
	if not territory_to_province:
		warnings.append("Chưa có phân công đội ngũ theo địa bàn.")
		return {}
	staff = frappe.get_all(
		"CRM Staff",
		filters={"is_active": 1, "territory": ["in", list(territory_to_province)]},
		fields=["territory", "target"],
		limit_page_length=0,
	)
	result: dict[str, dict[str, int]] = defaultdict(lambda: {"activeAdvisors": 0, "plannedThroughput": 0})
	for row in staff:
		province = territory_to_province.get(row.get("territory"))
		if province:
			result[province]["activeAdvisors"] += 1
			result[province]["plannedThroughput"] += round(_number(row.get("target")))
	return dict(result)


def _load_targets(admission_year: str, province_ids: list[str], warnings: list[str]) -> dict[str, float]:
	if not frappe.db.table_exists("CRM Target"):
		warnings.append("Chưa có nguồn chỉ tiêu theo địa bàn.")
		return {}
	rows = frappe.get_all(
		"CRM Target",
		filters={"admission_year": admission_year, "metric_key": ["in", ["enrollment", "enrollments"]]},
		fields=["planning_scope", "target_value", "status"],
		limit_page_length=0,
	)
	scope_ids = [row.get("planning_scope") for row in rows if row.get("planning_scope")]
	scopes = {
		row["name"]: row.get("province")
		for row in frappe.get_all(
			"CRM Planning Scope",
			filters={"name": ["in", scope_ids]},
			fields=["name", "province"],
			limit_page_length=0,
		)
	}
	result: dict[str, float] = {}
	for row in rows:
		province = scopes.get(row.get("planning_scope"))
		if row.get("status") == "Approved" and province in province_ids:
			result[str(province)] = _number(row.get("target_value"))
	if not result:
		warnings.append(
			"Chưa có chỉ tiêu nhập học theo địa bàn; tỷ lệ đạt chỉ tiêu dùng 0 khi chỉ tiêu canonical bằng 0."
		)
	return result


def _load_previous_students(
	admission_year: str, province_ids: list[str], warnings: list[str]
) -> dict[str, list[dict[str, Any]]]:
	previous_year = str(int(admission_year) - 1)
	try:
		rows = frappe.get_all(
			"CRM Student",
			filters={"admission_year": previous_year, "province": ["in", province_ids]},
			fields=STUDENT_FIELDS,
			limit_page_length=0,
		)
	except Exception:
		warnings.append("Không thể tải kỳ so sánh; các chỉ số thay đổi sẽ để trống.")
		return {}
	result: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in rows:
		result[row["province"]].append(dict(row))
	return result


def _build_province(
	province_id: str,
	name: str,
	rows: list[dict[str, Any]],
	previous: list[dict[str, Any]],
	target: float | None,
	workforce: dict[str, int] | None,
	as_of: datetime,
) -> dict[str, Any]:
	applications = len(rows)
	enrollments = sum(_is_enrolled(row) for row in rows)
	qualified = sum(_is_qualified(row) for row in rows)
	counselling = sum(_is_counselling(row) for row in rows)
	qualified = max(qualified, counselling, enrollments)
	counselling = max(counselling, enrollments)
	previous_applications = len(previous)
	previous_enrollments = sum(_is_enrolled(row) for row in previous)
	target_value = round(target or 0)
	conversion = _ratio(enrollments, applications)
	achievement = _ratio(enrollments, target_value) or 0.0
	active_advisors = workforce.get("activeAdvisors") if workforce else None
	planned_throughput = workforce.get("plannedThroughput") if workforce else None
	capacity = _ratio(max(applications - enrollments, 0), planned_throughput or 0)
	return {
		"id": province_id,
		"name": name,
		"applications": applications,
		"enrollments": enrollments,
		"enrollmentTarget": target_value,
		"targetAchievement": achievement,
		"conversion": conversion,
		"applicationChange": _change(applications, previous_applications),
		"enrollmentChange": _change(enrollments, previous_enrollments),
		"activeAdvisors": active_advisors,
		"capacity": capacity,
		"health": _health(achievement, conversion),
		"trend": _build_trend(rows, previous, as_of),
		"funnel": [
			{"id": stage_id, "stage": label, "value": value}
			for (stage_id, label), value in zip(
				FUNNEL_STAGES, (applications, qualified, counselling, enrollments), strict=True
			)
		],
		"capabilities": _capabilities(achievement, conversion, applications, qualified, counselling),
	}


def _build_trend(
	rows: list[dict[str, Any]], previous: list[dict[str, Any]], as_of: datetime
) -> list[dict[str, Any]]:
	months = _months(as_of)
	return [
		{
			"month": f"T{month.month}/{month.year}",
			"applications": _count_month(rows, month, "creation"),
			"enrollments": _count_month(rows, month, "enrollment_date", _is_enrolled),
			"previousApplications": _count_month(previous, month.replace(year=month.year - 1), "creation"),
		}
		for month in months
	]


def _months(as_of: datetime) -> list[datetime]:
	month = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
	result = []
	for _ in range(TREND_MONTHS):
		result.append(month)
		month = (month.replace(day=1) - timedelta(days=1)).replace(day=1)
	return list(reversed(result))


def _count_month(rows: list[dict[str, Any]], month: datetime, field: str, predicate: Any = None) -> int:
	return sum(
		1
		for row in rows
		if (value := _date(row.get(field)))
		and value.year == month.year
		and value.month == month.month
		and (not predicate or predicate(row))
	)


def _is_enrolled(row: dict[str, Any]) -> bool:
	return _fold(row.get("student_stage")) == "connected" or _fold(row.get("resolution")) == "created"


def _is_qualified(row: dict[str, Any]) -> bool:
	return _fold(row.get("student_stage")) in {"attempting", "qualified", "connected"} or _fold(
		row.get("processing_status")
	) in {"processing", "processed", "assigned"} or _is_enrolled(row)


def _is_counselling(row: dict[str, Any]) -> bool:
	return _fold(row.get("student_stage")) in {"attempting", "qualified", "connected"} or _fold(
		row.get("processing_status")
	) in {"processing", "assigned"} or _is_enrolled(row)


def _capabilities(
	achievement: float, conversion: float | None, applications: int, qualified: int, counselling: int
) -> dict[str, str]:
	return {
		"leadGeneration": _tone(_ratio(qualified, applications)),
		"counselling": _tone(_ratio(counselling, qualified)),
		"quality": _tone(_ratio(qualified, applications)),
		"conversion": _tone(conversion),
		"campaigns": _tone(_ratio(qualified, applications)),
		"productivity": _tone(achievement),
	}


def _health(achievement: float, conversion: float | None) -> str:
	return (
		"critical"
		if achievement < 60 or (conversion is not None and conversion < 10)
		else "watch"
		if achievement < 100
		else "good"
	)


def _tone(value: float | None) -> str:
	return "critical" if value is None or value < 40 else "watch" if value < 70 else "good"


def _build_priority_actions(provinces: list[dict[str, Any]]) -> list[dict[str, Any]]:
	items = []
	for province in provinces:
		if province["health"] == "critical":
			items.append(
				{
					"id": f"improve-{province['id']}",
					"title": f"Ưu tiên địa bàn {province['name']}",
					"detail": "Hiệu suất tuyển sinh đang dưới ngưỡng cần theo dõi.",
					"provinceId": province["id"],
					"priority": "Cao",
					"tone": "critical",
				}
			)
	return items


def _ratio(numerator: int, denominator: int) -> float | None:
	return round(numerator / denominator * 100, 1) if denominator else None


def _change(current: int, previous: int) -> float | None:
	return round((current - previous) / previous * 100, 1) if previous else None


def _number(value: Any) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _date(value: Any) -> datetime | None:
	if not value:
		return None
	try:
		parsed = frappe.utils.get_datetime(value)
		return (
			parsed.replace(tzinfo=LOCAL_TIMEZONE)
			if parsed.tzinfo is None
			else parsed.astimezone(LOCAL_TIMEZONE)
		)
	except (TypeError, ValueError):
		return None


def _now() -> datetime:
	return _date(frappe.utils.now_datetime()) or datetime.now(LOCAL_TIMEZONE)


def _fold(value: Any) -> str:
	text = unicodedata.normalize("NFKD", str(value or "").casefold())
	return "".join(char for char in text if not unicodedata.combining(char)).replace("đ", "d")
