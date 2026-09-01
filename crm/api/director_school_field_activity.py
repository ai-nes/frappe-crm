"""Read-only aggregate projection for the Director school field activity view.

The projection is intentionally conservative.  ``CRM School Activity`` is the
operational source for activity rows, while student attribution is only counted
when an append-only ``CRM Student Engagement Event`` points at that activity.
Fields that the current schema cannot prove (for example activity spend or
device acknowledgements) remain ``None``/unavailable instead of being inferred
from an unrelated campaign or from the current page size.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import frappe
from frappe import _

from crm.api.director_school_common import raise_api_error, require_director_access

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
QUERY_PAGE_SIZE = 5_000
ACTIVITY_LIMIT_DEFAULT = 50
UPCOMING_LIMIT_DEFAULT = 10
SUPPORTED_PERIODS = frozenset({"season", "6m", "12m"})
AMOUNT_UNITS = frozenset({"vnd", "thousand_vnd", "million_vnd"})

ACTIVITY_FIELDS = [
	"name",
	"high_school",
	"crm_campaign",
	"title",
	"admission_year",
	"activity_type",
	"activity_date",
	"scheduled_datetime",
	"owner_staff",
	"owning_team",
	"status",
	"attendance",
	"prospect_count",
	"contact_count",
	"application_count",
	"evidence_reference",
]
OPTIONAL_ACTIVITY_FIELDS = (
	"activity_cost",
	"activity_cost_unit",
	"cost_amount",
	"cost_unit",
	"expected_enrollment_min",
	"expected_enrollment_max",
	"forecast_confidence",
	"forecast_sample_size",
	"forecast_source",
)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_school_field_activity(
	admissionYear: str | int | None = None,
	scope: str = "all",
	period: str = "season",
	activityLimit: str | int | None = None,
	upcomingLimit: str | int | None = None,
	includeDevices: bool | str | None = True,
) -> dict[str, Any]:
	"""Return one consistent, permission-checked activity snapshot."""
	access = _request_access()
	year = _resolve_admission_year(admissionYear)
	period = _parse_period(period)
	activity_limit = _parse_limit(
		activityLimit, field="activityLimit", minimum=1, maximum=200, default=ACTIVITY_LIMIT_DEFAULT
	)
	upcoming_limit = _parse_limit(
		upcomingLimit, field="upcomingLimit", minimum=1, maximum=50, default=UPCOMING_LIMIT_DEFAULT
	)
	include_devices = _parse_boolean(includeDevices, default=True)
	scope_context = _normalize_scope(scope)
	_authorize_scope(scope_context, access)

	as_of = _now()
	year_config = _load_admission_year_config(year)
	period_start, period_end = _period_window(year, period, as_of, year_config)
	warnings: list[str] = []
	activity_rows, activities_source, plans_source = _load_activity_rows(
		year, scope_context, period_start, period_end, as_of
	)
	attribution, attribution_source = _load_attribution(activity_rows, warnings)
	schools, staff, activity_types = _load_lookups(activity_rows)

	completed_rows = [
		row
		for row in activity_rows
		if row.get("status") == "Completed"
		and _row_admission_year(row) == year
		and _in_window(_activity_datetime(row), period_start, period_end)
	]
	upcoming_rows = [
		row
		for row in activity_rows
		if row.get("status") in {"Planned", "Cancelled"}
		and _row_admission_year(row) == year
		and _activity_datetime(row) is not None
		and _activity_datetime(row) >= as_of
		and _in_window(_activity_datetime(row), period_start, period_end)
	]
	upcoming_rows.sort(key=lambda row: (_activity_datetime(row) or as_of, str(row.get("name") or "")))

	all_completed = [
		_build_completed_activity(
			row,
			attribution=attribution,
			schools=schools,
			staff=staff,
			activity_types=activity_types,
		)
		for row in completed_rows
	]
	completed = [
		_build_completed_activity(
			row,
			attribution=attribution,
			schools=schools,
			staff=staff,
			activity_types=activity_types,
		)
		for row in completed_rows[:activity_limit]
	]
	upcoming = [
		_build_upcoming_activity(
			row,
			schools=schools,
			activity_types=activity_types,
		)
		for row in upcoming_rows[:upcoming_limit]
	]

	device_sync = None
	device_source = "unavailable"
	unsynced = None
	if include_devices and access.get("roleState") != "guest":
		device_sync, device_source = _load_device_sync(warnings)
		if device_sync and device_source == "available":
			unsynced = _non_negative_int(device_sync.get("totalUnsyncedRecords"))

	data_quality = _build_data_quality(all_completed, staff, attribution=attribution)
	metric_values = [metric["value"] for metric in data_quality["seasonMetrics"]]
	data_quality_source = (
		"available"
		if metric_values and all(value is not None for value in metric_values)
		else "partial"
		if any(value is not None for value in metric_values)
		else "unavailable"
	)
	total_prospects = _load_total_prospects(year, scope_context)
	kpis = _build_kpis(all_completed, total_prospects=total_prospects, unsynced=unsynced)

	if attribution_source == "unavailable":
		warnings.append("Chưa có nguồn attribution chuẩn cho lead của hoạt động thực địa.")
	if data_quality_source == "unavailable":
		warnings.append("Chưa có nguồn đo chất lượng dữ liệu nhập thực địa.")
	if device_source == "unavailable":
		warnings.append("Nguồn đồng bộ thiết bị chưa được cấu hình; không suy diễn số pending/error.")
	if any(item["cost"]["amount"] is None for item in all_completed):
		warnings.append("Chi phí hoạt động chưa có nguồn dữ liệu theo từng hoạt động.")

	sources = {
		"activities": activities_source,
		"plans": plans_source,
		"dataQuality": data_quality_source,
		"deviceSync": device_source,
	}
	status = "available" if all(value == "available" for value in sources.values()) else "partial"
	return {
		"meta": {
			"admissionYear": _year_number(year, year_config),
			"scope": scope_context["id"],
			"scopeLabel": scope_context["label"],
			"period": period,
			"asOf": _as_iso(as_of),
			"timezone": "Asia/Ho_Chi_Minh",
			"status": status,
			"sources": sources,
			"warnings": _unique(warnings),
		},
		"kpis": kpis,
		"completedActivities": completed,
		"upcomingActivities": upcoming,
		"dataQuality": data_quality,
		"deviceSync": device_sync,
	}


def _request_access() -> dict[str, Any]:
	"""Allow the public dashboard shell only the unscoped aggregate snapshot."""
	user = getattr(getattr(frappe, "session", None), "user", None)
	if user == "Guest":
		return {"user": user, "roleState": "guest"}
	return require_director_access()


def _parse_admission_year(value: Any) -> str | None:
	if value in (None, ""):
		return None
	text = str(value).strip()
	if not re.fullmatch(r"\d{4}", text) or not 2000 <= int(text) <= 2100:
		raise_api_error(
			"INVALID_ADMISSION_YEAR",
			"Kỳ tuyển sinh phải là năm 4 chữ số trong khoảng 2000..2100.",
			frappe.ValidationError,
			422,
		)
	return text


def _parse_period(value: Any) -> str:
	text = "season" if value in (None, "") else str(value).strip().lower()
	if text not in SUPPORTED_PERIODS:
		raise_api_error("INVALID_QUERY", "Tham số period không hợp lệ.", frappe.ValidationError, 400)
	return text


def _parse_limit(value: Any, *, field: str, minimum: int, maximum: int, default: int) -> int:
	if value in (None, ""):
		return default
	if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value).strip()):
		raise_api_error("INVALID_QUERY", f"Tham số {field} không hợp lệ.", frappe.ValidationError, 400)
	number = int(value)
	if not minimum <= number <= maximum:
		raise_api_error("INVALID_QUERY", f"Tham số {field} không hợp lệ.", frappe.ValidationError, 400)
	return number


def _parse_boolean(value: Any, *, default: bool) -> bool:
	if value in (None, ""):
		return default
	if value is True or (isinstance(value, str) and value.strip().casefold() == "true"):
		return True
	if value is False or (isinstance(value, str) and value.strip().casefold() == "false"):
		return False
	raise_api_error("INVALID_QUERY", "Tham số includeDevices phải là boolean.", frappe.ValidationError, 400)
	return default


def _resolve_admission_year(value: Any = None) -> str:
	parsed = _parse_admission_year(value)
	if parsed:
		rows = _fetch_rows(
			"CRM Admission Year",
			filters={"name": parsed},
			fields=["name", "year_name", "start_date", "end_date"],
			order_by="name asc",
			limit=1,
		)
		if not rows:
			rows = _fetch_rows(
				"CRM Admission Year",
				filters={"year_name": parsed},
				fields=["name", "year_name", "start_date", "end_date"],
				order_by="name asc",
				limit=1,
			)
		if not rows:
			raise_api_error(
				"ADMISSION_YEAR_NOT_FOUND",
				"Không tồn tại dữ liệu cho kỳ tuyển sinh được yêu cầu.",
				frappe.DoesNotExistError,
				404,
			)
		return str(rows[0].get("name") or parsed)

	rows = _fetch_rows(
		"CRM Admission Year",
		filters={"is_active": 1},
		fields=["name", "year_name", "start_date", "end_date"],
		order_by="year_name desc, name desc",
		limit=2,
	)
	if len(rows) != 1:
		raise_api_error(
			"INVALID_ADMISSION_YEAR",
			"Cần cấu hình đúng một kỳ tuyển sinh đang hoạt động.",
			frappe.ValidationError,
			422,
		)
	return str(rows[0].get("name") or rows[0].get("year_name"))


def _normalize_scope(value: Any = "all") -> dict[str, Any]:
	text = str(value or "all").strip()
	if not text or len(text) > 64 or any(ord(char) < 32 for char in text):
		raise_api_error("INVALID_QUERY", "Tham số scope không hợp lệ.", frappe.ValidationError, 400)
	if text.casefold() == "all":
		return {"id": "all", "label": "Toàn bộ cơ sở", "kind": "all", "value": None}

	campus = _lookup_scope_row("CRM Campus", text, ["name", "campus_name", "campus_code"])
	if campus:
		return {
			"id": campus["name"],
			"label": campus.get("campus_name") or campus["name"],
			"kind": "campus",
			"value": campus["name"],
		}

	territory = _lookup_scope_row("CRM Territory", text, ["name", "territory_name", "territory_code"])
	if territory:
		return {
			"id": territory["name"],
			"label": territory.get("territory_name") or territory["name"],
			"kind": "territory",
			"value": territory["name"],
		}

	province = _lookup_scope_row("CRM Province", text, ["name", "province_name", "province_code"])
	if province:
		return {
			"id": province["name"],
			"label": province.get("province_name") or province["name"],
			"kind": "province",
			"value": province["name"],
		}

	raise_api_error("INVALID_QUERY", "Scope không tồn tại hoặc không được hỗ trợ.", frappe.ValidationError, 400)
	return {}


def _lookup_scope_row(doctype: str, value: str, fields: list[str]) -> dict[str, Any] | None:
	rows = _fetch_rows(doctype, filters={"name": value}, fields=fields, limit=1, allow_missing=True)
	if rows:
		return rows[0]
	code_field = {"CRM Campus": "campus_code", "CRM Territory": "territory_code", "CRM Province": "province_code"}[doctype]
	rows = _fetch_rows(doctype, filters={code_field: value}, fields=fields, limit=1, allow_missing=True)
	return rows[0] if rows else None


def _authorize_scope(scope: dict[str, Any], access: dict[str, Any]) -> None:
	if access.get("roleState") == "guest":
		if scope.get("kind") == "all":
			return
		raise_api_error("FORBIDDEN", "Guest chỉ được truy cập snapshot toàn bộ cơ sở.", frappe.PermissionError, 403)
	if scope.get("kind") == "all" or access.get("roleState") in {"platform_superuser", "system_manager"}:
		return
	user = getattr(getattr(frappe, "session", None), "user", None)
	staff_rows = _fetch_rows(
		"CRM Staff",
		filters={"user": user, "is_active": 1},
		fields=["name", "campus", "territory"],
		limit=1,
		allow_missing=True,
	)
	staff = staff_rows[0] if staff_rows else {}
	if scope.get("kind") == "campus" and staff.get("campus") == scope.get("value"):
		return
	if scope.get("kind") == "territory" and staff.get("territory") == scope.get("value"):
		return
	if scope.get("kind") == "province" and _staff_has_province_scope(staff.get("territory"), scope.get("value")):
		return
	raise_api_error("FORBIDDEN", "Scope không nằm trong phạm vi được cấp quyền.", frappe.PermissionError, 403)


def _staff_has_province_scope(territory: str | None, province: str | None) -> bool:
	if not territory or not province or not _table_exists("CRM Territory Geography Assignment"):
		return False
	rows = _fetch_rows(
		"CRM Territory Geography Assignment",
		filters={"territory": territory, "geography_type": "Province", "status": "Active"},
		fields=["geography", "effective_from", "effective_until"],
		allow_missing=True,
	)
	today = _now().date()
	return any(
		str(row.get("geography")) == str(province)
		and (not row.get("effective_from") or str(row["effective_from"]) <= str(today))
		and (not row.get("effective_until") or str(row["effective_until"]) >= str(today))
		for row in rows
	)


def _load_admission_year_config(year: str) -> dict[str, Any]:
	rows = _fetch_rows(
		"CRM Admission Year",
		filters={"name": year},
		fields=["name", "year_name", "start_date", "end_date"],
		limit=1,
		allow_missing=True,
	)
	return rows[0] if rows else {}


def _period_window(year: str, period: str, as_of: datetime, config: dict[str, Any]) -> tuple[datetime, datetime]:
	if period == "season":
		try:
			year_number = int(config.get("year_name") or year)
		except (TypeError, ValueError):
			year_number = as_of.year
		start_date = _coerce_date(config.get("start_date")) or date(year_number, 1, 1)
		end_date = _coerce_date(config.get("end_date")) or date(year_number, 12, 31)
		return _at_start(start_date), _at_start(end_date + timedelta(days=1))
	days = 182 if period == "6m" else 365
	return as_of - timedelta(days=days), as_of + timedelta(seconds=1)


def _load_activity_rows(
	year: str,
	scope: dict[str, Any],
	period_start: datetime,
	period_end: datetime,
	as_of: datetime,
) -> tuple[list[dict[str, Any]], str, str]:
	filters = _scope_activity_filters(scope)
	rows = _fetch_rows(
		"CRM School Activity",
		filters=filters,
		fields=_activity_query_fields(),
		order_by="activity_date desc, scheduled_datetime desc, name desc",
		allow_missing=False,
	)
	rows = [
		row
		for row in rows
		if _row_admission_year(row) == year
		and (
			(row.get("status") == "Completed" and _in_window(_activity_datetime(row), period_start, period_end))
			or (
				row.get("status") in {"Planned", "Cancelled"}
				and _activity_datetime(row) is not None
				and _activity_datetime(row) >= as_of
				and _in_window(_activity_datetime(row), period_start, period_end)
			)
		)
	]
	return rows, "available", "available"


def _scope_activity_filters(scope: dict[str, Any]) -> dict[str, Any]:
	kind = scope.get("kind")
	if kind == "all":
		return {}
	if kind in {"campus", "territory"}:
		field = "campus" if kind == "campus" else "territory"
		staff = _fetch_rows(
			"CRM Staff",
			filters={field: scope.get("value"), "is_active": 1},
			fields=["name"],
			allow_missing=True,
		)
		return {"owner_staff": ["in", [row["name"] for row in staff]]} if staff else {"name": "__no_scope__"}
	if kind == "province":
		schools = _fetch_rows(
			"CRM High School",
			filters={"province": scope.get("value")},
			fields=["name"],
			allow_missing=True,
		)
		return {"high_school": ["in", [row["name"] for row in schools]]} if schools else {"name": "__no_scope__"}
	return {"name": "__no_scope__"}


def _load_attribution(rows: list[dict[str, Any]], warnings: list[str]) -> tuple[dict[str, dict[str, Any]], str]:
	result = {
		str(row["name"]): {
			"students": set(),
			"verified": set(),
		"qualified": set(),
		"enrolled": set(),
		"phone_reachable": set(),
		"consent": set(),
		"quality": "unavailable",
		}
		for row in rows
		if row.get("name")
	}
	if not rows or not _table_exists("CRM Student Engagement Event"):
		return _apply_reported_leads(result, rows), "partial" if any(row.get("prospect_count") is not None for row in rows) else "unavailable"

	activity_names = list(result)
	events = _fetch_rows(
		"CRM Student Engagement Event",
		filters={"school_activity": ["in", activity_names], "event_type": "School Activity"},
		fields=["name", "student", "school_activity", "consent_state", "supersedes"],
		allow_missing=True,
	)
	superseded = {str(row.get("supersedes")) for row in events if row.get("supersedes")}
	events = [row for row in events if row.get("name") not in superseded]
	student_ids = {row.get("student") for row in events if row.get("student")}
	students = _load_attributed_students(student_ids)
	student_by_id = {str(row.get("name")): row for row in students if row.get("name")}
	applications = _load_attributed_applications(student_ids)
	applications_by_student: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in applications:
		if row.get("student"):
			applications_by_student[str(row["student"])].append(row)

	for event in events:
		activity_name = str(event.get("school_activity") or "")
		student = str(event.get("student") or "")
		if activity_name not in result or not student:
			continue
		item = result[activity_name]
		item["students"].add(student)
		if str(event.get("consent_state") or "").casefold() == "granted":
			item["verified"].add(student)
			item["consent"].add(student)
		student_row = student_by_id.get(student)
		if student_row:
			if student_row.get("phone"):
				item["phone_reachable"].add(student)
			if _is_qualified(student_row):
				item["qualified"].add(student)
			if _is_enrolled(student_row, applications_by_student.get(student, [])):
				item["enrolled"].add(student)

	for item in result.values():
		if item["students"]:
			item["quality"] = "verified" if item["students"] <= set(student_by_id) else "partial"
			item["student_metrics_available"] = item["students"] <= set(student_by_id)

	_apply_reported_leads(result, rows)
	return result, "available" if events else (
		"partial" if any(row.get("prospect_count") is not None for row in rows) else "unavailable"
	)


def _apply_reported_leads(result: dict[str, dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
	for row in rows:
		item = result.get(str(row.get("name")))
		if item is not None and row.get("prospect_count") is not None:
			item["leads"] = _non_negative_int(row.get("prospect_count"))
			item["quality"] = "partial"
	return result


def _load_attributed_students(student_ids: set[Any]) -> list[dict[str, Any]]:
	if not student_ids or not _table_exists("CRM Student"):
		return []
	return _fetch_rows(
		"CRM Student",
		filters={"name": ["in", list(student_ids)]},
		fields=["name", "lifecycle_stage", "enrollment_status", "phone"],
		allow_missing=True,
	)


def _load_attributed_applications(student_ids: set[Any]) -> list[dict[str, Any]]:
	if not student_ids or not _table_exists("CRM Admission Application"):
		return []
	return _fetch_rows(
		"CRM Admission Application",
		filters={"student": ["in", list(student_ids)]},
		fields=["student", "status"],
		allow_missing=True,
	)


def _load_lookups(rows: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
	school_names = sorted({str(row.get("high_school")) for row in rows if row.get("high_school")})
	staff_names = sorted({str(row.get("owner_staff")) for row in rows if row.get("owner_staff")})
	type_names = sorted({str(row.get("activity_type")) for row in rows if row.get("activity_type")})
	schools = {
		str(row["name"]): dict(row)
		for row in _fetch_rows(
			"CRM High School",
			filters={"name": ["in", school_names]} if school_names else {"name": "__none__"},
			fields=["name", "school_name", "province", "address"],
			allow_missing=True,
		)
		if row.get("name")
	}
	staff = {
		str(row["name"]): dict(row)
		for row in _fetch_rows(
			"CRM Staff",
			filters={"name": ["in", staff_names]} if staff_names else {"name": "__none__"},
			fields=["name", "full_name"],
			allow_missing=True,
		)
		if row.get("name")
	}
	activity_types = {
		str(row["name"]): str(row.get("term_name") or row["name"])
		for row in _fetch_rows(
			"CRM Term",
			filters={"name": ["in", type_names], "category": "activity_type"} if type_names else {"name": "__none__"},
			fields=["name", "term_name"],
			allow_missing=True,
		)
		if row.get("name")
	}
	return schools, staff, activity_types


def _build_completed_activity(
	row: dict[str, Any],
	*,
	attribution: dict[str, dict[str, Any]],
	schools: dict[str, dict[str, Any]],
	staff: dict[str, dict[str, Any]],
	activity_types: dict[str, str],
) -> dict[str, Any]:
	activity_id = str(row.get("name"))
	school = schools.get(str(row.get("high_school")), {})
	type_id = str(row.get("activity_type") or "unknown")
	type_label = activity_types.get(type_id, type_id)
	school_name = str(school.get("school_name") or row.get("high_school") or "")
	title = str(row.get("title") or "").strip() or _join_title(type_label, school_name)
	short_name = school_name or type_label or title
	attr = attribution.get(activity_id, {})
	students = set(attr.get("students") or [])
	leads = len(students) if students else _optional_int(attr.get("leads"), row.get("prospect_count"))
	verified = len(attr["verified"]) if students and "verified" in attr else None
	metrics_available = attr.get("student_metrics_available", True)
	qualified = len(attr["qualified"]) if students and metrics_available else None
	enrolled = len(attr["enrolled"]) if students and metrics_available else None
	cost = _activity_cost(row)
	cost_per_enrollment = _cost_per_enrollment(cost, enrolled)
	return {
		"id": activity_id,
		"activityType": type_id,
		"title": title,
		"shortName": short_name,
		"occurredAt": _as_iso(_activity_datetime(row)) or "",
		"dateLabel": _date_label(_activity_datetime(row)),
		"locationId": str(row.get("high_school")) if row.get("high_school") else None,
		"location": str(school.get("province") or school_name or "-"),
		"ownerId": str(row.get("owner_staff")) if row.get("owner_staff") else None,
		"owner": (staff.get(str(row.get("owner_staff"))) or {}).get("full_name"),
		"cost": cost,
		"leads": leads,
		"verifiedLeads": verified,
		"verifiedRate": _ratio(verified, leads),
		"qualified": qualified,
		"enrolled": enrolled,
		"costPerEnrollment": cost_per_enrollment,
		"status": "completed",
		"dataQuality": attr.get("quality") or ("partial" if leads is not None else "unavailable"),
	}


def _build_upcoming_activity(
	row: dict[str, Any], *, schools: dict[str, dict[str, Any]], activity_types: dict[str, str]
) -> dict[str, Any]:
	school = schools.get(str(row.get("high_school")), {})
	type_id = str(row.get("activity_type") or "unknown")
	type_label = activity_types.get(type_id, type_id)
	school_name = str(school.get("school_name") or row.get("high_school") or "")
	return {
		"id": str(row.get("name")),
		"activityType": type_id,
		"title": str(row.get("title") or "").strip() or _join_title(type_label, school_name),
		"locationId": str(row.get("high_school")) if row.get("high_school") else None,
		"location": school_name or str(school.get("province") or "-"),
		"scheduledAt": _as_iso(_activity_datetime(row)) or "",
		"dateLabel": _date_label(_activity_datetime(row)),
		"expectedEnrollment": {
			"min": _non_negative_int(row.get("expected_enrollment_min")),
			"max": _non_negative_int(row.get("expected_enrollment_max")),
			"unit": "students",
		},
		"confidence": _bounded_percent(row.get("forecast_confidence")),
		"historicalSampleSize": _non_negative_int(row.get("forecast_sample_size")),
		"status": "cancelled" if row.get("status") == "Cancelled" else "planned",
		"source": str(row.get("forecast_source") or "manual"),
		"evidence": _evidence(row.get("evidence_reference")),
	}


def _build_kpis(rows: list[dict[str, Any]], *, total_prospects: int | None, unsynced: int | None) -> list[dict[str, Any]]:
	leads = _sum_known(row.get("leads") for row in rows)
	enrolled = _sum_known(row.get("enrolled") for row in rows)
	total_cost = _sum_costs(row.get("cost") for row in rows)
	cost_per_enrollment = round(total_cost / enrolled / 1_000_000, 1) if total_cost is not None and enrolled else None
	conversion = _ratio(enrolled, leads)
	share = _ratio(leads, total_prospects)
	return [
		_kpi("activity-count", "Hoạt động đã triển khai", len(rows), "activities", tone="primary"),
		_kpi("field-leads", "Hồ sơ thu được", leads, "leads", share_of_prospects=share, tone="success"),
		_kpi("cost-per-enrollment", "Chi phí mỗi học sinh nhập học", cost_per_enrollment, "million_vnd", tone="success"),
		_kpi("field-conversion", "Tỷ lệ hồ sơ chuyển thành nhập học", conversion, "percent", tone="primary"),
		_kpi("unsynced-records", "Hồ sơ chưa đồng bộ", unsynced, "records", tone="error"),
	]


def _kpi(
	id: str,
	label: str,
	value: int | float | None,
	unit: str,
	*,
	share_of_prospects: float | None = None,
	tone: str,
) -> dict[str, Any]:
	return {
		"id": id,
		"label": label,
		"value": value,
		"unit": unit,
		"change": None,
		"changeUnit": None,
		"comparison": None,
		"shareOfProspects": share_of_prospects,
		"benchmark": None,
		"detail": None,
		"tone": tone,
	}


def _build_data_quality(
	rows: list[dict[str, Any]],
	staff: dict[str, dict[str, Any]],
	*,
	attribution: dict[str, dict[str, Any]],
) -> dict[str, Any]:
	records_by_owner: dict[str, int] = defaultdict(int)
	students: set[str] = set()
	phone_reachable: set[str] = set()
	consent: set[str] = set()
	for row in rows:
		owner_id = str(row.get("ownerId") or "")
		if owner_id and row.get("leads") is not None:
			records_by_owner[owner_id] += int(row["leads"])
		attr = attribution.get(str(row.get("id")), {})
		students.update(attr.get("students") or [])
		phone_reachable.update(attr.get("phone_reachable") or [])
		consent.update(attr.get("consent") or [])
	team = [
		{
			"userId": owner_id,
			"name": str((staff.get(owner_id) or {}).get("full_name") or owner_id),
			"records": count,
			"secondsPerRecord": None,
			"duplicateRate": None,
			"missingRate": None,
		}
		for owner_id, count in sorted(records_by_owner.items())
	]
	phone_rate = _ratio(len(phone_reachable), len(students)) if students else None
	consent_rate = _ratio(len(consent), len(students)) if students else None
	return {
		"unsyncedRecords": 0,
		"team": team,
		"seasonMetrics": [
			{"id": "reachable-phone", "label": "Số điện thoại liên lạc được", "value": phone_rate, "target": 95.0, "unit": "percent", "status": _metric_status(phone_rate, 95.0)},
			{"id": "data-consent", "label": "Đồng ý xử lý dữ liệu", "value": consent_rate, "target": 100.0, "unit": "percent", "status": _metric_status(consent_rate, 100.0)},
			{"id": "receipt-image", "label": "Có ảnh phiếu đính kèm", "value": None, "target": 80.0, "unit": "percent", "status": "unavailable"},
		],
		"attention": None,
	}


def _metric_status(value: float | None, target: float | None) -> str:
	if value is None or target is None:
		return "unavailable"
	return "meets_target" if value >= target else "below_target"


def _load_total_prospects(year: str, scope: dict[str, Any]) -> int | None:
	if not _table_exists("CRM Student"):
		return None
	filters: dict[str, Any] = {"admission_year": year}
	if scope.get("kind") == "campus":
		filters["branch"] = scope.get("value")
	elif scope.get("kind") == "province":
		schools = _fetch_rows(
			"CRM High School",
			filters={"province": scope.get("value")},
			fields=["name"],
			allow_missing=True,
		)
		if not schools:
			return 0
		filters["high_school"] = ["in", [row["name"] for row in schools]]
	rows = _fetch_rows(
		"CRM Student",
		filters=filters,
		fields=["name", "lifecycle_stage"],
		allow_missing=True,
	)
	return len([row for row in rows if str(row.get("lifecycle_stage") or "") != "Lost"])


def _load_device_sync(warnings: list[str]) -> tuple[dict[str, Any] | None, str]:
	# No device-sync DocType exists in the current CRM schema. Keep this seam
	# explicit so a future source can be added without changing the response
	# contract or manufacturing pending/error counts here.
	return None, "unavailable"


def _activity_query_fields() -> list[str]:
	fields = list(ACTIVITY_FIELDS)
	try:
		meta = frappe.get_meta("CRM School Activity")
		fields.extend(field for field in OPTIONAL_ACTIVITY_FIELDS if meta.has_field(field))
	except (AttributeError, frappe.DoesNotExistError):
		pass
	return fields


def _activity_cost(row: dict[str, Any]) -> dict[str, Any]:
	for field, unit_field in (("activity_cost", "activity_cost_unit"), ("cost_amount", "cost_unit")):
		if row.get(field) in (None, ""):
			continue
		unit = str(row.get(unit_field) or "vnd")
		return {"amount": _number(row.get(field)), "unit": unit if unit in AMOUNT_UNITS else "vnd"}
	return {"amount": None, "unit": "vnd"}


def _cost_per_enrollment(cost: dict[str, Any], enrolled: int | None) -> dict[str, Any]:
	if cost.get("amount") is None or not enrolled:
		return {"amount": None, "unit": cost.get("unit") or "vnd"}
	return {"amount": round(float(cost["amount"]) / enrolled, 2), "unit": cost.get("unit") or "vnd"}


def _sum_costs(costs: Any) -> float | None:
	items = list(costs)
	if not items or any(item is None or item.get("amount") is None for item in items):
		return None
	return sum(_to_vnd(float(item["amount"]), item.get("unit")) for item in items)


def _to_vnd(amount: float, unit: str | None) -> float:
	if unit == "million_vnd":
		return amount * 1_000_000
	if unit == "thousand_vnd":
		return amount * 1_000
	return amount


def _is_qualified(row: dict[str, Any]) -> bool:
	return str(row.get("lifecycle_stage") or "").casefold() in {"mql", "applicant", "enrolled"}


def _is_enrolled(student: dict[str, Any], applications: list[dict[str, Any]]) -> bool:
	if str(student.get("lifecycle_stage") or "").casefold() == "enrolled":
		return True
	return any(str(row.get("status") or "").casefold() == "enrolled" for row in applications)


def _row_admission_year(row: dict[str, Any]) -> str:
	return str(row.get("admission_year") or "")


def _activity_datetime(row: dict[str, Any]) -> datetime | None:
	value = row.get("scheduled_datetime") or row.get("activity_date")
	if isinstance(value, date) and not isinstance(value, datetime):
		return datetime.combine(value, time.min, tzinfo=LOCAL_TIMEZONE)
	return _coerce_datetime(value)


def _load_year_number(value: Any) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return 0


def _year_number(year: str, config: dict[str, Any]) -> int:
	return _load_year_number(config.get("year_name") or year)


def _in_window(value: datetime | None, start: datetime, end: datetime) -> bool:
	return value is not None and start <= value < end


def _at_start(value: date) -> datetime:
	return datetime.combine(value, time.min, tzinfo=LOCAL_TIMEZONE)


def _coerce_date(value: Any) -> date | None:
	if not value:
		return None
	try:
		return frappe.utils.getdate(value)
	except (AttributeError, TypeError, ValueError, OverflowError):
		return None


def _coerce_datetime(value: Any) -> datetime | None:
	if not value:
		return None
	try:
		parsed = frappe.utils.get_datetime(value)
		if parsed.tzinfo is None:
			return parsed.replace(tzinfo=LOCAL_TIMEZONE)
		return parsed.astimezone(LOCAL_TIMEZONE)
	except (AttributeError, TypeError, ValueError, OverflowError):
		return None


def _now() -> datetime:
	return _coerce_datetime(frappe.utils.now_datetime()) or datetime.now(LOCAL_TIMEZONE)


def _as_iso(value: Any) -> str | None:
	parsed = _coerce_datetime(value)
	return parsed.isoformat(timespec="seconds") if parsed else None


def _date_label(value: datetime | None) -> str | None:
	return value.strftime("%d/%m") if value else None


def _join_title(activity_type: str, school_name: str) -> str:
	parts = [part for part in (activity_type, school_name) if part and part != "unknown"]
	return " — ".join(parts) or "Hoạt động thực địa"


def _number(value: Any) -> float | None:
	try:
		number = float(value)
	except (TypeError, ValueError):
		return None
	return round(number, 2) if isinstance(value, Decimal) else number


def _bounded_percent(value: Any) -> float | None:
	number = _number(value)
	return round(min(100.0, max(0.0, number)), 1) if number is not None else None


def _evidence(value: Any) -> list[str]:
	if value in (None, ""):
		return []
	return [str(value)]


def _non_negative_int(value: Any) -> int | None:
	try:
		return max(0, int(value))
	except (TypeError, ValueError):
		return None


def _optional_int(primary: Any, fallback: Any) -> int | None:
	return _non_negative_int(primary) if primary not in (None, "") else _non_negative_int(fallback)


def _sum_known(values: Any) -> int | None:
	items = [value for value in values if value is not None]
	return sum(items) if items else None


def _ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
	if numerator is None or denominator in (None, 0):
		return None
	return round(float(numerator) / float(denominator) * 100, 1)


def _unique(values: list[str]) -> list[str]:
	return list(dict.fromkeys(value for value in values if value))


def _fetch_rows(
	doctype: str,
	*,
	filters: dict[str, Any],
	fields: list[str],
	order_by: str | None = None,
	limit: int | None = None,
	allow_missing: bool = False,
) -> list[dict[str, Any]]:
	if not _table_exists(doctype):
		if allow_missing:
			return []
		raise_api_error(
			"DIRECTOR_SCHOOL_FIELD_ACTIVITY_UNAVAILABLE",
			"Không thể tải nguồn dữ liệu hoạt động trường và thực địa.",
			frappe.ValidationError,
			503,
		)
	rows: list[dict[str, Any]] = []
	page_size = min(limit or QUERY_PAGE_SIZE, QUERY_PAGE_SIZE)
	start = 0
	while True:
		query: dict[str, Any] = {
			"filters": filters,
			"fields": fields,
			"limit_start": start,
			"limit_page_length": page_size,
		}
		if order_by:
			query["order_by"] = order_by
		try:
			batch = frappe.get_all(doctype, **query)
		except Exception:
			if allow_missing:
				return []
			raise_api_error(
				"DIRECTOR_SCHOOL_FIELD_ACTIVITY_UNAVAILABLE",
				"Không thể tải nguồn dữ liệu hoạt động trường và thực địa.",
				frappe.ValidationError,
				503,
			)
		rows.extend(dict(row) for row in batch)
		if len(batch) < page_size or (limit is not None and len(rows) >= limit):
			return rows[:limit] if limit is not None else rows
		start += len(batch)


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except (AttributeError, frappe.DoesNotExistError):
		return False
