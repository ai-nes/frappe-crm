"""Aggregate API for the Director admission overview dashboard.

The endpoint intentionally exposes reporting aggregates only.  It is public
because the dashboard is consumed by a guest-facing shell, so no student
identity or row-level operational detail may be added to this module.
"""

from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import frappe
from frappe import _

from crm.api.director_students import _resolve_admission_year

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
QUERY_PAGE_SIZE = 5_000
TREND_RANGES = ("7d", "30d", "year")
STAGE_ORDER = ("prospect", "engaged", "qualified", "counselling", "application", "accepted", "enrolled")
STAGE_LABELS = {
	"prospect": "Hồ sơ tiềm năng",
	"engaged": "Đã tương tác",
	"qualified": "Đủ điều kiện",
	"counselling": "Đang tư vấn",
	"application": "Đã nộp hồ sơ",
	"accepted": "Đã trúng tuyển",
	"enrolled": "Đã nhập học",
}
STATUS_TO_STAGE = {
	"moi": "prospect",
	"lead moi": "prospect",
	"co trien vong": "qualified",
	"dang tu van": "counselling",
	"da nop ho so": "application",
	"da xac nhan": "accepted",
	"da trung tuyen": "accepted",
	"da nhap hoc": "enrolled",
	"khong quan tam": "lost",
	"sai so": "lost",
	"tu choi": "lost",
	"new": "prospect",
	"processing": "counselling",
	"processed": "qualified",
	"assigned": "counselling",
	"created": "enrolled",
	"invalid": "lost",
	"duplicate": "lost",
	"spam": "lost",
	"failed": "lost",
}
APPLICATION_STAGE = {
	"Submitted": "application",
	"Under Review": "application",
	"Accepted": "accepted",
	"Enrolled": "enrolled",
	"Lost": "lost",
	"Withdrawn": "lost",
}
REGIONS = (
	("southeast", "Đông Nam Bộ", ("dong nam bo", "southeast", "south east")),
	("red-river", "Đồng bằng sông Hồng", ("dong bang song hong", "red river", "red-river")),
	("mekong", "Đồng bằng sông Cửu Long", ("dong bang song cuu long", "mekong", "tay nam bo")),
	("central", "Bắc & Nam Trung Bộ", ("trung bo", "central", "bac trung bo", "nam trung bo")),
)
MEKONG_PROVINCES = (
	"an giang",
	"bac lieu",
	"ben tre",
	"ca mau",
	"can tho",
	"dong thap",
	"hau giang",
	"kien giang",
	"long an",
	"soc trang",
	"tien giang",
	"tra vinh",
	"vinh long",
)
RED_RIVER_PROVINCES = (
	"bac giang",
	"bac kan",
	"bac ninh",
	"cao bang",
	"dien bien",
	"ha giang",
	"ha nam",
	"ha noi",
	"hai duong",
	"hai phong",
	"hoa binh",
	"hung yen",
	"lai chau",
	"lang son",
	"lao cai",
	"nam dinh",
	"ninh binh",
	"phu tho",
	"quang ninh",
	"son la",
	"thai binh",
	"thai nguyen",
	"tuyen quang",
	"vinh phuc",
	"yen bai",
)
CENTRAL_PROVINCES = (
	"dak nong",
	"dak lak",
	"da nang",
	"gia lai",
	"ha tinh",
	"khanh hoa",
	"kon tum",
	"lam dong",
	"nghe an",
	"ninh thuan",
	"phu yen",
	"quang binh",
	"quang nam",
	"quang ngai",
	"quang tri",
	"thanh hoa",
	"thua thien hue",
)
SOUTHEAST_PROVINCES = (
	"ba ria",
	"ba ria vung tau",
	"binh duong",
	"binh phuoc",
	"dong nai",
	"ho chi minh",
	"tay ninh",
)
SOURCES = (
	("facebook", "Quảng cáo Facebook", ("facebook", "meta", "social")),
	("school-tour", "Tư vấn tại trường", ("school", "truong", "career talk", "tu van", "referral")),
	("zalo", "Zalo OA", ("zalo",)),
	("website", "Website / Biểu mẫu", ("website", "web", "form", "landing", "google", "tiktok", "search")),
	("open-day", "Ngày hội tuyển sinh", ("open day", "open-day", "ngay hoi", "event", "offline")),
)
KPI_DEFINITIONS = (
	("prospects", "Tổng hồ sơ tiềm năng", "prospect", "primary", "so với kỳ trước"),
	("qualified", "Hồ sơ đủ điều kiện", "qualified", "info", "so với tuần trước"),
	("applicants", "Đã nộp hồ sơ", "application", "warning", "so với kỳ trước"),
	("accepted", "Đã trúng tuyển", "accepted", "info", "so với kỳ trước"),
	("enrollment", "Đã nhập học", "enrolled", "success", "so với kỳ trước"),
)
STUDENT_FIELDS = [
	"name",
	"admission_year",
	"processing_status",
	"resolution",
	"branch",
	"province",
	"ward",
	"high_school",
	"source",
	"advertising_channel",
	"creation",
	"modified",
	"enrollment_date",
]
APPLICATION_FIELDS = ["name", "student", "status", "submitted_at", "enrolled_at", "campus"]
INTERACTION_FIELDS = ["name", "student", "crm_contact", "interaction_datetime", "sla_response_sealed"]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_overview(
	admissionYear: str | int | None = None,
	scope: str = "all",
	trendRange: str = "30d",
) -> dict[str, Any]:
	"""Return the complete aggregate snapshot consumed by the Director home page."""
	admission_year = _resolve_overview_admission_year(admissionYear)
	scope_context = _normalize_scope(scope)
	default_range = _normalize_trend_range(trendRange)
	as_of = _now()
	if scope_context.get("territory"):
		scope_context["territory_geographies"] = _load_territory_geographies(
			scope_context["territory"], as_of
		)
	students = _load_students(admission_year, scope_context)
	lookups = _load_lookups(students)
	students = _filter_students_by_scope(students, scope_context, lookups)
	applications = _load_applications(admission_year, scope_context)
	student_ids = {row.get("name") for row in students if row.get("name")}
	applications = [
		row for row in applications if not row.get("student") or row.get("student") in student_ids
	]
	targets = _load_targets(admission_year, scope_context)
	interactions = _load_interactions(students, as_of)

	student_records = _build_student_records(students, applications, lookups, interactions)
	counts = _stage_counts(student_records)
	market = _build_market_overview(student_records, lookups, as_of)
	return {
		"meta": _build_meta(admission_year, scope_context, as_of),
		"kpis": _build_kpis(counts, targets),
		"forecast": _build_forecast(
			counts["enrolled"], targets, student_records, as_of, _year_number(admission_year)
		),
		"briefing": _build_briefing(market, counts),
		"pipeline": _build_pipeline(counts),
		"admissionsTrend": _build_trend(student_records, default_range, as_of, _year_number(admission_year)),
		"marketOverview": market,
		"sourcePerformance": _build_source_performance(student_records),
		"weeklyActivity": _build_weekly_activity(interactions, as_of),
	}


def _resolve_overview_admission_year(value: str | int | None) -> str:
	try:
		return _resolve_admission_year(value)
	except frappe.ValidationError:
		_raise_api_error(
			"ADMISSION_YEAR_NOT_FOUND",
			"Không tìm thấy kỳ tuyển sinh.",
			getattr(frappe, "DoesNotExistError", frappe.ValidationError),
			404,
		)
		return ""


def _normalize_trend_range(value: Any) -> str:
	result = str(value or "30d").strip().lower()
	if result not in TREND_RANGES:
		_raise_api_error(
			"INVALID_QUERY", "Tham số trendRange phải là 7d, 30d hoặc year.", frappe.ValidationError, 400
		)
	return result


def _normalize_scope(value: Any) -> dict[str, Any]:
	result = str(value or "all").strip()
	if not result or len(result) > 64 or any(ord(char) < 32 for char in result):
		_raise_api_error("INVALID_QUERY", "Tham số scope không hợp lệ.", frappe.ValidationError, 400)
	if result.casefold() == "all":
		return {
			"id": "all",
			"label": "Toàn bộ cơ sở",
			"branch": None,
			"region": None,
			"territory": None,
		}

	label = result
	branch = result
	region = None
	scope_id = result
	territory = None
	rows = []
	try:
		rows = frappe.get_all(
			"CRM Campus",
			filters={"name": result},
			fields=["name", "campus_name", "campus_code"],
			limit_page_length=1,
		)
		if not rows:
			rows = frappe.get_all(
				"CRM Campus",
				filters={"campus_code": result},
				fields=["name", "campus_name", "campus_code"],
				limit_page_length=1,
			)
		if rows:
			branch = rows[0].get("name") or result
			label = rows[0].get("campus_name") or branch
	except Exception:
		# Scope remains an exact branch value when the optional Campus lookup is
		# unavailable.  Frappe filters still parameterize the value safely.
		pass
	if not rows:
		try:
			territory_rows = frappe.get_all(
				"CRM Territory",
				filters={"name": result},
				fields=["name", "territory_name", "territory_code", "region"],
				limit_page_length=1,
			)
			if not territory_rows:
				territory_rows = frappe.get_all(
					"CRM Territory",
					filters={"territory_code": result},
					fields=["name", "territory_name", "territory_code", "region"],
					limit_page_length=1,
				)
			if territory_rows:
				territory = territory_rows[0]
				scope_id = territory.get("name") or result
				label = territory.get("territory_name") or label
				branch = None
				region = territory.get("region")
		except Exception:
			pass
	return {
		"id": scope_id,
		"label": label,
		"branch": branch,
		"region": region,
		"territory": scope_id if territory else None,
	}


def _load_students(admission_year: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
	filters: dict[str, Any] = {"admission_year": admission_year}
	if scope.get("branch"):
		filters["branch"] = scope["branch"]
	try:
		return _fetch_rows(
			"CRM Lead",
			filters=filters,
			fields=STUDENT_FIELDS,
			order_by="creation asc, name asc",
		)
	except Exception:
		_raise_api_error(
			"DIRECTOR_OVERVIEW_UNAVAILABLE",
			"Không thể tải dữ liệu tổng quan tuyển sinh.",
			frappe.ValidationError,
			503,
		)
		return []


def _load_applications(admission_year: str, scope: dict[str, Any]) -> list[dict[str, Any]]:
	if not _table_exists("CRM Admission Application"):
		_raise_api_error(
			"DIRECTOR_OVERVIEW_UNAVAILABLE",
			"Không thể tải dữ liệu hồ sơ đăng ký tuyển sinh.",
			frappe.ValidationError,
			503,
		)
	filters: dict[str, Any] = {"admission_year": admission_year}
	if scope.get("branch"):
		filters["campus"] = scope["branch"]
	try:
		return _fetch_rows(
			"CRM Admission Application",
			filters=filters,
			fields=APPLICATION_FIELDS,
			order_by="modified desc, name desc",
		)
	except Exception:
		_raise_api_error(
			"DIRECTOR_OVERVIEW_UNAVAILABLE",
			"Không thể tải dữ liệu hồ sơ đăng ký tuyển sinh.",
			frappe.ValidationError,
			503,
		)
		return []


def _load_interactions(
	students: list[dict[str, Any]], _as_of: datetime | None = None
) -> list[dict[str, Any]]:
	"""Load all interaction evidence; weekly activity applies its own date window."""
	student_ids = [row.get("name") for row in students if row.get("name")]
	if not student_ids:
		return []
	if not _table_exists("CRM Interaction"):
		_raise_api_error(
			"DIRECTOR_OVERVIEW_UNAVAILABLE",
			"Không thể tải dữ liệu tương tác tuyển sinh.",
			frappe.ValidationError,
			503,
		)
	try:
		return _fetch_rows(
			"CRM Interaction",
			filters={"student": ["in", student_ids]},
			fields=INTERACTION_FIELDS,
			order_by="interaction_datetime asc, name asc",
		)
	except Exception:
		_raise_api_error(
			"DIRECTOR_OVERVIEW_UNAVAILABLE",
			"Không thể tải dữ liệu tương tác tuyển sinh.",
			frappe.ValidationError,
			503,
		)
		return []


def _load_territory_geographies(territory: str, as_of: datetime) -> list[dict[str, Any]]:
	if not _table_exists("CRM Territory Geography Assignment"):
		_raise_api_error(
			"DIRECTOR_OVERVIEW_UNAVAILABLE",
			"Không thể xác định phạm vi địa lý của territory.",
			frappe.ValidationError,
			503,
		)
	try:
		rows = _fetch_rows(
			"CRM Territory Geography Assignment",
			filters={"territory": territory, "status": "Active"},
			fields=["geography_type", "geography", "effective_from", "effective_until"],
			order_by="revision desc, effective_from desc, name desc",
		)
	except Exception:
		_raise_api_error(
			"DIRECTOR_OVERVIEW_UNAVAILABLE",
			"Không thể tải phạm vi địa lý của territory.",
			frappe.ValidationError,
			503,
		)
		return []

	current_date = as_of.date()
	current_rows = [row for row in rows if _assignment_is_current(row, current_date)]
	if not current_rows:
		_raise_api_error(
			"DIRECTOR_OVERVIEW_UNAVAILABLE",
			"Territory chưa có phạm vi địa lý đang hiệu lực.",
			frappe.ValidationError,
			503,
		)
	return current_rows


def _assignment_is_current(row: dict[str, Any], current_date: date) -> bool:
	start = _coerce_datetime(row.get("effective_from"))
	end = _coerce_datetime(row.get("effective_until"))
	return (not start or start.date() <= current_date) and (not end or end.date() >= current_date)


def _load_lookups(students: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
	province_ids = {row.get("province") for row in students if row.get("province")}
	source_ids = {row.get("source") for row in students if row.get("source")}
	lookups: dict[str, dict[str, Any]] = {"provinces": {}, "sources": {}}
	if province_ids:
		try:
			lookups["provinces"] = {
				row.get("name"): dict(row)
				for row in _fetch_rows(
					"CRM Province",
					filters={"name": ["in", list(province_ids)]},
					fields=["name", "province_name", "province_code", "region"],
					order_by="name asc",
				)
				if row.get("name")
			}
		except Exception:
			pass
	if source_ids:
		try:
			lookups["sources"] = {
				row.get("name"): dict(row)
				for row in _fetch_rows(
					"CRM Lead Source",
					filters={"name": ["in", list(source_ids)]},
					fields=["name", "source_name", "channel_family"],
					order_by="name asc",
				)
				if row.get("name")
			}
		except Exception:
			pass
	return lookups


def _filter_students_by_scope(
	students: list[dict[str, Any]], scope: dict[str, Any], lookups: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
	if scope.get("territory"):
		assignments = scope.get("territory_geographies") or []
		return [
			row
			for row in students
			if any(_student_matches_geography(row, assignment, lookups) for assignment in assignments)
		]
	if not scope.get("region"):
		return students
	target_region = _region_id(scope["region"], {"provinces": {}, "sources": {}})
	return [row for row in students if _region_id(row.get("province"), lookups) == target_region]


def _student_matches_geography(
	student: dict[str, Any], assignment: dict[str, Any], lookups: dict[str, dict[str, Any]]
) -> bool:
	geography = _fold(assignment.get("geography"))
	if not geography:
		return False
	geography_type = _fold(assignment.get("geography_type"))
	province = lookups.get("provinces", {}).get(student.get("province"), {})
	student_province = {
		_fold(student.get("province")),
		_fold(province.get("province_name")),
		_fold(province.get("province_code")),
	}
	if geography_type == "province":
		return geography in student_province
	if geography_type == "region":
		return _region_id(assignment.get("geography"), {"provinces": {}, "sources": {}}) == _region_id(
			student.get("province"), lookups
		)
	if geography_type == "ward":
		return geography == _fold(student.get("ward"))
	return False


def _load_targets(admission_year: str, scope: dict[str, Any]) -> dict[str, float]:
	if not _table_exists("CRM Target"):
		return {}
	filters: dict[str, Any] = {
		"admission_year": admission_year,
		"period_type": "Annual",
		"status": "Approved",
	}
	try:
		rows = _fetch_rows(
			"CRM Target",
			filters=filters,
			fields=[
				"metric_key",
				"target_value",
				"planning_scope",
				"modified",
				"version",
			],
			order_by="version desc, modified desc, name desc",
		)
	except Exception:
		return {}

	result: dict[str, float] = {}
	for row in rows:
		if not _target_matches_scope(row, scope):
			continue
		metric = _metric_key(row.get("metric_key"))
		if metric and metric not in result:
			result[metric] = _number(row.get("target_value"))
	return result


def _target_matches_scope(row: dict[str, Any], scope: dict[str, Any]) -> bool:
	values = {_fold(row.get("planning_scope"))} if row.get("planning_scope") else set()
	scope_key = _fold(row.get("planning_scope"))
	if scope["id"] == "all":
		if scope_key == "national":
			return True
		return bool(values & {"all", "national", "toan bo"})
	if scope.get("branch"):
		branch = _fold(scope["branch"])
		return branch in values or _fold(scope["id"]) in values or scope_key == f"campus:{branch}"
	region = _fold(scope.get("region"))
	territory = _fold(scope["id"])
	return (
		region in values
		or territory in values
		or scope_key == f"region:{region}"
		or scope_key == f"territory:{territory}"
	)


def _build_student_records(
	students: list[dict[str, Any]],
	applications: list[dict[str, Any]],
	lookups: dict[str, dict[str, Any]] | None = None,
	interactions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
	applications_by_student: dict[str, dict[str, Any]] = defaultdict(
		lambda: {"stages": [], "submitted_at": [], "enrolled_at": []}
	)
	interaction_students = {row.get("student") for row in (interactions or []) if row.get("student")}
	for application in applications:
		student = application.get("student")
		stage = APPLICATION_STAGE.get(str(application.get("status") or "").strip())
		if student and stage:
			applications_by_student[student]["stages"].append(stage)
			if application.get("submitted_at"):
				applications_by_student[student]["submitted_at"].append(application.get("submitted_at"))
			if application.get("enrolled_at"):
				applications_by_student[student]["enrolled_at"].append(application.get("enrolled_at"))

	records = []
	for row in students:
		student_id = row.get("name")
		if not student_id:
			continue
		status_stage = STATUS_TO_STAGE.get(_fold(row.get("processing_status")))
		if str(row.get("resolution") or "").casefold() == "created":
			status_stage = "enrolled"
		application_data = applications_by_student.get(student_id, {})
		stages = set(application_data.get("stages", []))
		if status_stage:
			stages.add(status_stage)
		if student_id in interaction_students:
			stages.add("engaged")
		stages.discard("lost")
		if not stages and status_stage == "lost":
			continue
		if not stages:
			stages.add("prospect")
		source = row.get("source") or row.get("advertising_channel")
		if lookups:
			source_row = lookups.get("sources", {}).get(source, {})
			source = source_row.get("source_name") or source_row.get("channel_family") or source
		enrolled_dates = [_coerce_datetime(value) for value in application_data.get("enrolled_at", [])]
		enrolled_dates = [value for value in enrolled_dates if value]
		records.append(
			{
				"id": student_id,
				"stages": stages,
				"province": row.get("province"),
				"source": source,
				"created_at": _coerce_datetime(row.get("creation")),
				"applicant_at": _first_datetime(application_data.get("submitted_at", [])),
				"enrolled_at": min(enrolled_dates, default=None)
				or _coerce_datetime(row.get("enrollment_date")),
				"high_school": row.get("high_school"),
			}
		)
	return records


def _stage_counts(records: list[dict[str, Any]]) -> dict[str, int]:
	counts = {stage: 0 for stage in STAGE_ORDER}
	for record in records:
		stages = record["stages"]
		counts["prospect"] += 1
		if stages & {"engaged", "qualified", "counselling", "application", "accepted", "enrolled"}:
			counts["engaged"] += 1
		if stages & {"qualified", "counselling", "application", "accepted", "enrolled"}:
			counts["qualified"] += 1
		if stages & {"counselling", "application", "accepted", "enrolled"}:
			counts["counselling"] += 1
		if stages & {"application", "accepted", "enrolled"}:
			counts["application"] += 1
		if stages & {"accepted", "enrolled"}:
			counts["accepted"] += 1
		if "enrolled" in stages:
			counts["enrolled"] += 1
	return counts


def _build_meta(admission_year: str, scope: dict[str, Any], as_of: datetime) -> dict[str, Any]:
	return {
		"admissionYear": _year_number(admission_year),
		"scope": scope["id"],
		"scopeLabel": scope["label"],
		"asOf": _as_iso(as_of),
		"freshnessLabel": "Dữ liệu cập nhật vừa xong",
		"timezone": "Asia/Ho_Chi_Minh",
	}


def _build_kpis(
	counts: dict[str, int],
	targets: dict[str, float],
) -> list[dict[str, Any]]:
	result = []
	for metric_id, label, stage, tone, helper in KPI_DEFINITIONS:
		value = counts[stage]
		target = targets.get(metric_id)
		# Current CRM projections do not retain a complete historical aggregate
		# snapshot.  Do not compare the cumulative total with a recent cohort.
		change_value = None
		result.append(
			{
				"id": metric_id,
				"label": label,
				"value": _format_number(value),
				"target": _format_number(target) if target is not None else "—",
				"achievement": _format_percent(_percentage(value, target)) if target else "—",
				"change": _format_percent(change_value, signed=True) if change_value is not None else "—",
				"helper": helper,
				"tone": tone,
				"numericValue": value,
				"targetValue": target,
				"changeValue": change_value,
				"changeUnit": "percent",
			}
		)
	return result


def _build_pipeline(counts: dict[str, int]) -> dict[str, Any]:
	prospects = counts["prospect"]
	stages = []
	previous = prospects
	previous_value = prospects
	for index, stage in enumerate(STAGE_ORDER):
		value = min(previous, counts[stage])
		previous = value
		conversion = 100.0 if index == 0 else _percentage(value, previous_value)
		previous_value = value
		stages.append(
			{
				"id": stage,
				"label": STAGE_LABELS[stage],
				"value": _format_number(value),
				"percentage": round(_percentage(value, prospects)) if prospects else 0,
				"conversion": _format_percent(conversion),
			}
		)

	drops = []
	for index in range(1, len(stages)):
		from_stage = stages[index - 1]
		to_stage = stages[index]
		drops.append((float(from_stage["percentage"]) - float(to_stage["percentage"]), from_stage, to_stage))
	biggest = max(drops, key=lambda item: item[0], default=(0, stages[0], stages[0]))
	return {
		"stages": stages,
		"summary": {
			"prospects": counts["prospect"],
			"accepted": counts["accepted"],
			"enrolled": counts["enrolled"],
			"enrollmentRate": round(_percentage(counts["enrolled"], counts["prospect"]), 1)
			if counts["prospect"]
			else 0.0,
		},
		"biggestDrop": {
			"fromStageId": biggest[1]["id"],
			"fromLabel": biggest[1]["label"],
			"toStageId": biggest[2]["id"],
			"toLabel": biggest[2]["label"],
			"differencePoints": round(biggest[0]),
		},
	}


def _build_forecast(
	enrolled: int,
	targets: dict[str, float],
	records: list[dict[str, Any]],
	as_of: datetime,
	admission_year: int | None = None,
) -> dict[str, Any]:
	target = targets.get("enrollment", 0.0)
	reporting_year = admission_year or as_of.year
	actual_by_month = Counter()
	for record in records:
		if "enrolled" not in record["stages"]:
			continue
		when = record.get("enrolled_at") or record.get("created_at")
		if when:
			if when.year == reporting_year:
				actual_by_month[when.month] += 1
	points = []
	cumulative = 0
	for index in range(1, 11):
		month = index
		cumulative += actual_by_month.get(month, 0)
		is_historical = reporting_year < as_of.year
		is_current = reporting_year == as_of.year
		actual = cumulative if is_historical or (is_current and month <= as_of.month) else None
		forecast = cumulative
		points.append(
			{
				"label": f"T{index}",
				"actual": actual,
				"forecast": forecast,
				"target": round(target * index / 10) if target else 0,
			}
		)
	return {
		"summary": {
			"actual": enrolled,
			"forecast": enrolled,
			"target": target,
			"confidence": 0,
			"gapToTarget": max(round(target - enrolled), 0),
		},
		"points": points,
	}


def _build_trend(
	records: list[dict[str, Any]],
	default_range: str,
	as_of: datetime,
	admission_year: int | None = None,
) -> dict[str, Any]:
	return {
		"defaultRange": default_range,
		"ranges": {key: _trend_range(records, key, as_of, admission_year) for key in TREND_RANGES},
	}


def _trend_range(
	records: list[dict[str, Any]],
	range_key: str,
	as_of: datetime,
	admission_year: int | None = None,
) -> dict[str, Any]:
	day_start = as_of.replace(hour=0, minute=0, second=0, microsecond=0)
	if range_key == "7d":
		buckets = [
			(day_start + timedelta(days=index - 6), day_start + timedelta(days=index - 5))
			for index in range(7)
		]
		labels = tuple(_day_label(day_start + timedelta(days=index - 6)) for index in range(7))
	elif range_key == "30d":
		boundaries = (0, 7, 14, 21, 30)
		buckets = [
			(
				day_start - timedelta(days=30 - boundaries[index]),
				day_start - timedelta(days=30 - boundaries[index + 1]),
			)
			for index in range(4)
		]
		labels = tuple(f"Tuần {index}" for index in range(1, 5))
	else:
		reporting_year = admission_year or as_of.year
		year_start = day_start.replace(year=reporting_year, month=1, day=1)
		month_count = as_of.month if reporting_year == as_of.year else 12
		buckets = [
			(_add_months(year_start, index), _add_months(year_start, index + 1))
			for index in range(month_count)
		]
		labels = tuple(f"T{index}" for index in range(1, month_count + 1))
	points = []
	for label, (start, end) in zip(labels, buckets, strict=True):
		created = [record for record in records if _in_range(record.get("created_at"), start, end)]
		applicants = sum(
			_in_range(record.get("applicant_at") or record.get("created_at"), start, end)
			for record in records
		)
		enrolled = sum(
			_in_range(record.get("enrolled_at") or record.get("created_at"), start, end)
			for record in records
			if "enrolled" in record["stages"]
		)
		points.append(
			{"label": label, "newLeads": len(created), "applicants": applicants, "enrolled": enrolled}
		)
	return {
		"points": points,
		"totals": {
			"newLeads": sum(point["newLeads"] for point in points),
			"applicants": sum(point["applicants"] for point in points),
			"enrolled": sum(point["enrolled"] for point in points),
		},
	}


def _build_market_overview(
	records: list[dict[str, Any]], lookups: dict[str, dict[str, Any]], as_of: datetime
) -> list[dict[str, Any]]:
	grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for record in records:
		grouped[_region_id(record.get("province"), lookups)].append(record)
	items = []
	for region_id, name, _region_aliases in REGIONS:
		region_records = grouped.get(region_id, [])
		prospects = len(region_records)
		enrolled = sum("enrolled" in record["stages"] for record in region_records)
		growth = _record_growth(region_records, as_of)
		items.append(
			{
				"id": region_id,
				"name": name,
				"prospects": _format_number(prospects),
				"enrolled": _format_number(enrolled),
				"conversion": _format_percent(_percentage(enrolled, prospects)),
				"growth": _format_percent(growth, signed=True) if growth is not None else "—",
				"coverage": round(
					_percentage(sum(bool(record.get("high_school")) for record in region_records), prospects)
				)
				if prospects
				else 0,
				"tone": "danger"
				if growth is not None and growth < 0
				else "success"
				if growth is not None and growth > 0
				else "info",
				"prospectsValue": prospects,
				"enrolledValue": enrolled,
				"conversionValue": _percentage(enrolled, prospects),
				"growthValue": growth,
			}
		)
	return items


def _build_source_performance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
	items = []
	for source_id, label, _aliases in SOURCES:
		matches = [record for record in records if _source_id(record.get("source")) == source_id]
		leads = len(matches)
		applicants = sum(
			bool(record["stages"] & {"application", "accepted", "enrolled"}) for record in matches
		)
		enrolled = sum("enrolled" in record["stages"] for record in matches)
		total = len(records)
		items.append(
			{
				"id": source_id,
				"label": label,
				"leads": _format_number(leads),
				"applicants": _format_number(applicants),
				"enrolled": _format_number(enrolled),
				"share": round(_percentage(leads, total)),
				"leadsValue": leads,
				"applicantsValue": applicants,
				"enrolledValue": enrolled,
			}
		)
	return items


def _build_weekly_activity(interactions: list[dict[str, Any]], as_of: datetime) -> dict[str, Any]:
	start = as_of.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
	points = []
	for index in range(7):
		day_start = start + timedelta(days=index)
		day_end = day_start + timedelta(days=1)
		rows = [
			row
			for row in interactions
			if _in_range(_coerce_datetime(row.get("interaction_datetime")), day_start, day_end)
		]
		sla = (
			_percentage(sum(bool(row.get("sla_response_sealed")) for row in rows), len(rows)) if rows else 0.0
		)
		points.append({"label": _day_label(day_start), "interactions": len(rows), "sla": round(sla, 1)})
	total = sum(point["interactions"] for point in points)
	return {
		"points": points,
		"totalInteractions": total,
		"averageSla": round(sum(point["sla"] for point in points) / 7, 1),
		"changePercent": _activity_change(interactions, as_of),
	}


def _build_briefing(market: list[dict[str, Any]], counts: dict[str, int]) -> dict[str, Any]:
	risk = min(
		market,
		key=lambda item: item.get("growthValue") if item.get("growthValue") is not None else 0,
		default=None,
	)
	if risk and risk.get("growthValue") is not None and risk["growthValue"] < 0:
		alert = {
			"id": f"{risk['id']}-risk",
			"type": "risk",
			"title": f"Tăng trưởng tại {risk['name']} đang giảm",
			"description": "Tốc độ tạo hồ sơ trong kỳ gần đây thấp hơn kỳ so sánh.",
			"evidence": f"Mức thay đổi hiện tại là {risk['growth']}.",
			"metric": risk["growth"],
			"href": "/director/regional-performance",
		}
	else:
		alert = {
			"id": "pipeline-overview",
			"type": "opportunity",
			"title": "Theo dõi phễu tuyển sinh",
			"description": "Tiếp tục ưu tiên các hồ sơ đã đủ điều kiện nhưng chưa nộp hồ sơ.",
			"evidence": f"Hiện có {counts['qualified'] - counts['application']} hồ sơ ở nhóm này.",
			"metric": _format_number(max(counts["qualified"] - counts["application"], 0)),
			"href": "/director/admission-funnel",
		}
	return {
		"alert": alert,
		"priorityAction": {
			"id": "follow-up-qualified",
			"title": "Chăm sóc nhóm đủ điều kiện",
			"description": "Ưu tiên xử lý các hồ sơ đủ điều kiện chưa chuyển sang bước nộp hồ sơ.",
			"impact": f"{_format_number(max(counts['qualified'] - counts['application'], 0))} hồ sơ cần theo dõi",
			"href": "/director/students",
		},
	}


def _record_growth(records: list[dict[str, Any]], as_of: datetime) -> float | None:
	current_start = as_of - timedelta(days=30)
	previous_start = as_of - timedelta(days=60)
	current = sum(_in_range(record.get("created_at"), current_start, as_of) for record in records)
	previous = sum(_in_range(record.get("created_at"), previous_start, current_start) for record in records)
	return _percent_change(current, previous)


def _activity_change(interactions: list[dict[str, Any]], as_of: datetime) -> float:
	day_end = as_of.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
	current_start = day_end - timedelta(days=7)
	previous_start = day_end - timedelta(days=14)
	current = sum(
		_in_range(_coerce_datetime(row.get("interaction_datetime")), current_start, as_of)
		for row in interactions
	)
	previous = sum(
		_in_range(_coerce_datetime(row.get("interaction_datetime")), previous_start, current_start)
		for row in interactions
	)
	return round(_percent_change(current, previous) or 0.0, 1)


def _region_id(value: Any, lookups: dict[str, dict[str, Any]]) -> str:
	province = lookups.get("provinces", {}).get(value, {})
	province_name = _fold(province.get("province_name") or value)
	if any(name in province_name for name in MEKONG_PROVINCES):
		return "mekong"
	if any(name in province_name for name in SOUTHEAST_PROVINCES):
		return "southeast"
	if any(name in province_name for name in RED_RIVER_PROVINCES):
		return "red-river"
	if any(name in province_name for name in CENTRAL_PROVINCES):
		return "central"
	text = _fold(province.get("region") or value)
	for region_id, _name, aliases in REGIONS:
		if any(alias in text for alias in aliases):
			return region_id
	if "mien bac" in text or "bac bo" in text:
		return "red-river"
	if "mien trung" in text:
		return "central"
	if "mien nam" in text:
		return "southeast"
	return "unmapped"


def _source_id(value: Any) -> str | None:
	text = _fold(value)
	for source_id, _label, aliases in SOURCES:
		if any(alias in text for alias in aliases):
			return source_id
	return None


def _metric_key(value: Any) -> str | None:
	text = _fold(value).replace("_", " ").replace("-", " ")
	aliases = {
		"prospects": ("prospect", "lead", "leads", "ho so tiem nang"),
		"qualified": ("qualified", "ho so du dieu kien"),
		"applicants": ("applicant", "application", "applications", "da nop ho so"),
		"accepted": ("accepted", "admitted", "trung tuyen"),
		"enrollment": ("enrollment", "enrolled", "nhap hoc"),
	}
	for metric, candidates in aliases.items():
		if any(candidate in text for candidate in candidates):
			return metric
	return None


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except (AttributeError, getattr(frappe, "DoesNotExistError", Exception)):
		return False


def _fetch_rows(
	doctype: str,
	*,
	filters: dict[str, Any],
	fields: list[str],
	order_by: str | None = None,
) -> list[dict[str, Any]]:
	"""Read a complete result set in bounded pages for aggregate calculations."""
	rows: list[dict[str, Any]] = []
	limit_start = 0
	while True:
		query = {
			"filters": filters,
			"fields": fields,
			"limit_start": limit_start,
			"limit_page_length": QUERY_PAGE_SIZE,
		}
		if order_by:
			query["order_by"] = order_by
		batch = frappe.get_all(doctype, **query)
		rows.extend(dict(row) for row in batch)
		if len(batch) < QUERY_PAGE_SIZE:
			return rows
		limit_start += len(batch)


def _coerce_datetime(value: Any) -> datetime | None:
	if not value:
		return None
	try:
		parsed = frappe.utils.get_datetime(value)
		if parsed.tzinfo is None:
			return parsed.replace(tzinfo=LOCAL_TIMEZONE)
		return parsed.astimezone(LOCAL_TIMEZONE)
	except (AttributeError, TypeError, ValueError):
		return None


def _now() -> datetime:
	return _coerce_datetime(frappe.utils.now_datetime()) or datetime.now(LOCAL_TIMEZONE)


def _in_range(value: datetime | None, start: datetime, end: datetime) -> bool:
	return bool(value and start <= value < end)


def _year_number(value: Any) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		try:
			name = frappe.db.get_value("CRM Admission Year", value, "year_name")
			return int(name)
		except (TypeError, ValueError, AttributeError):
			return 0


def _fold(value: Any) -> str:
	text = unicodedata.normalize("NFKD", str(value or "").casefold())
	return "".join(char for char in text if not unicodedata.combining(char)).replace("đ", "d")


def _number(value: Any) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _percentage(numerator: float, denominator: float) -> float:
	return round(numerator / denominator * 100, 1) if denominator else 0.0


def _percent_change(current: float, previous: float) -> float | None:
	return round((current - previous) / previous * 100, 1) if previous else None


def _format_number(value: float | int) -> str:
	return f"{round(value):,}".replace(",", ".")


def _format_percent(value: float | None, signed: bool = False) -> str:
	if value is None:
		return "—"
	return f"{value:+.1f}%".replace(".", ",") if signed else f"{value:.1f}%".replace(".", ",")


def _as_iso(value: Any) -> str | None:
	parsed = _coerce_datetime(value)
	return parsed.isoformat(timespec="seconds") if parsed else None


def _day_label(value: datetime) -> str:
	return ("T2", "T3", "T4", "T5", "T6", "T7", "CN")[value.weekday()]


def _add_months(value: datetime, months: int) -> datetime:
	month_index = value.year * 12 + value.month - 1 + months
	year, month_index = divmod(month_index, 12)
	return value.replace(year=year, month=month_index + 1, day=1)


def _first_datetime(values: list[Any]) -> datetime | None:
	parsed_values = [parsed for value in values if (parsed := _coerce_datetime(value))]
	return min(parsed_values, default=None)


def _raise_api_error(code: str, message: str, exception: type[Exception], status: int) -> None:
	try:
		if getattr(frappe, "local", None) and isinstance(getattr(frappe.local, "response", None), dict):
			frappe.local.response["error"] = {"code": code, "message": message}
			frappe.local.response["http_status_code"] = status
	except (AttributeError, TypeError):
		pass
	frappe.throw(_(message), exception)
