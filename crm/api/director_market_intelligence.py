from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict
from typing import Any

import frappe
from frappe.exceptions import QueryDeadlockError, QueryTimeoutError
from pymysql import MySQLError

from crm.api.director_school_common import (
	METRICS,
	REGIONS,
	parse_boolean,
	parse_enum,
	parse_limit,
	raise_api_error,
	resolve_admission_year,
)

_PAGE_SIZE = 500
_MAX_ROWS = 20_000
_SNAPSHOT_ORDER = "snapshot_date desc, recorded_at desc, revision desc, modified desc, name desc"
_SOURCE_ERRORS = (frappe.PermissionError, frappe.DoesNotExistError, QueryDeadlockError, QueryTimeoutError, MySQLError)
# The Director market map is intentionally scoped to the seven active provinces
# configured by the dashboard. Keep this scope in the backend so every metric
# in the response uses the same source-of-truth boundary.
PRIORITY_PROVINCE_CODES = (
	"VN_KHANH_HOA",
	"VN_DAK_LAK",
	"VN_LAM_DONG",
	"VN_DONG_NAI",
	"VN_HO_CHI_MINH",
	"VN_TAY_NINH",
	"VN_DONG_THAP",
)
PROVINCE_GEOMETRY_CODE_BY_SOURCE_CODE = {
	"VN_KHANH_HOA": "56",
	"VN_DAK_LAK": "66",
	"VN_LAM_DONG": "68",
	"VN_DONG_NAI": "75",
	"VN_HO_CHI_MINH": "79",
	"VN_TAY_NINH": "80",
	"VN_DONG_THAP": "82",
}
PROVINCE_REGION_BY_SOURCE_CODE = {
	"VN_KHANH_HOA": "central",
	"VN_DAK_LAK": "highlands",
	"VN_LAM_DONG": "highlands",
	"VN_DONG_NAI": "south",
	"VN_HO_CHI_MINH": "south",
	"VN_TAY_NINH": "south",
	"VN_DONG_THAP": "mekong",
}


class MarketPrimarySourceUnavailable(RuntimeError):
	pass


def _permission_rows(doctype: str, *, filters=None, fields=None, order_by="name asc", max_rows=_MAX_ROWS):
	rows = []
	for start in range(0, max_rows, _PAGE_SIZE):
		page = frappe.get_list(
			doctype,
			filters=filters or {},
			fields=fields or ["name"],
			order_by=order_by,
			limit_start=start,
			limit_page_length=min(_PAGE_SIZE, max_rows - start),
		)
		rows.extend(dict(row) for row in page)
		if len(page) < _PAGE_SIZE:
			return rows, False
	return rows, True


def _load_sources(admission_year: str):
	failed = set()
	try:
		provinces, provinces_capped = _permission_rows(
			"CRM Province",
			filters={"province_code": ["in", list(PRIORITY_PROVINCE_CODES)]},
			fields=["name", "province_code", "province_name", "region"],
		)
		schools, schools_capped = _permission_rows(
			"CRM High School",
			fields=[
				"name", "school_name", "school_code", "school_tier", "boarding_type",
				"province", "ward", "latitude", "longitude", "is_key_account",
			],
			order_by="province asc, school_code asc, name asc",
		)
	except _SOURCE_ERRORS as exc:
		raise MarketPrimarySourceUnavailable("province_or_school") from exc
	if provinces_capped or schools_capped:
		raise MarketPrimarySourceUnavailable("province_or_school_limit")

	def supporting(key, loader):
		try:
			rows, capped = loader()
			if capped:
				failed.add(key)
			return rows
		except _SOURCE_ERRORS:
			failed.add(key)
			return []

	wards = supporting(
		"wards",
		lambda: _permission_rows(
			"CRM Ward", fields=["name", "ward_code", "ward_name", "province"]
		),
	)
	students = supporting(
		"students",
		lambda: _permission_rows(
			"CRM Student",
			filters={"admission_year": admission_year},
			fields=["name", "high_school", "province", "student_stage"],
			order_by="name asc",
		),
	)
	snapshots = supporting(
		"snapshots",
		lambda: _permission_rows(
			"CRM High School Annual Snapshot",
			filters={
				"admission_year": admission_year,
				"period_type": "Annual",
				"verification_status": "Verified",
			},
			fields=[
				"name", "high_school", "admission_year", "snapshot_date", "recorded_at",
				"revision", "modified", "applicant_count", "enrolled_count", "student_count",
				"conversion_rate", "enrollment_rate", "forecast_count", "verification_status",
			],
			order_by=_SNAPSHOT_ORDER,
		),
	)
	return {
		"provinces": provinces,
		"schools": schools,
		"wards": wards,
		"students": students,
		"snapshots": snapshots,
	}, failed


def _sortable(value: Any) -> tuple[int, str]:
	return (0, "") if value in (None, "") else (1, str(value))


def _latest_snapshots(rows):
	latest = {}
	for row in sorted(
		rows,
		key=lambda item: (
			_sortable(item.get("snapshot_date")),
			_sortable(item.get("recorded_at")),
			int(item.get("revision") or 0),
			_sortable(item.get("modified")),
			str(item.get("name") or ""),
		),
		reverse=True,
	):
		if row.get("verification_status") == "Verified" and row.get("high_school") not in latest:
			latest[row.get("high_school")] = row
	return latest


def _fold(value: Any) -> str:
	text = unicodedata.normalize("NFKD", str(value or "").lower())
	return "".join(char for char in text if not unicodedata.combining(char)).replace("đ", "d")


def _geometry_province_code(value: Any) -> str | None:
	code = str(value or "").strip()
	return PROVINCE_GEOMETRY_CODE_BY_SOURCE_CODE.get(code, code or None)


def _region_key(value: Any, province_code: Any = None) -> str | None:
	source_region = str(value or "").strip().upper()
	province_region = PROVINCE_REGION_BY_SOURCE_CODE.get(str(province_code or "").strip())
	if source_region == "MB":
		return "north"
	if source_region == "MT":
		return province_region or "central"
	if source_region == "MN":
		return province_region or "south"

	text = _fold(value)
	if "bac" in text:
		return "north"
	if "tay nguyen" in text or "highland" in text:
		return "highlands"
	if "mekong" in text or "tay nam" in text or "dong bang song cuu long" in text:
		return "mekong"
	if "trung" in text:
		return "central"
	if "nam" in text:
		return "south"
	return province_region


def _ratio(numerator: int, denominator: int) -> float | None:
	return round(numerator / denominator * 100, 2) if denominator else None


def _source_revision(sources) -> str:
	payload = {
		key: [json.dumps(row, default=str, sort_keys=True) for row in rows]
		for key, rows in sources.items()
	}
	return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def _latest_as_of(rows) -> str | None:
	values = [str(row.get("snapshot_date") or row.get("recorded_at")) for row in rows if row and (row.get("snapshot_date") or row.get("recorded_at"))]
	return max(values) if values else None


def _build_overview(sources, failed, *, admission_year, region, metric, include_schools, school_limit):
	province_by_name = {row.get("name"): row for row in sources["provinces"]}
	ward_by_name = {row.get("name"): row for row in sources["wards"]}
	latest = _latest_snapshots(sources["snapshots"])
	students_available = "students" not in failed
	student_ids_by_school = defaultdict(set)
	student_ids_by_province = defaultdict(set)
	for row in sources["students"]:
		student_id = row.get("name")
		if not student_id:
			continue
		if row.get("high_school"):
			student_ids_by_school[row["high_school"]].add(student_id)
		if row.get("province"):
			student_ids_by_province[row["province"]].add(student_id)

	schools_by_province = defaultdict(list)
	for school in sources["schools"]:
		schools_by_province[school.get("province")].append(school)

	provinces = []
	for province_name, province in sorted(province_by_name.items(), key=lambda item: (str(item[1].get("province_code") or ""), item[0])):
		province_code = _geometry_province_code(province.get("province_code"))
		region_key = _region_key(province.get("region"), province.get("province_code"))
		if region != "all" and region_key != region:
			continue
		schools = schools_by_province.get(province_name, [])
		applicants = sum(int((latest.get(row.get("name")) or {}).get("applicant_count") or 0) for row in schools)
		enrolled = sum(int((latest.get(row.get("name")) or {}).get("enrolled_count") or 0) for row in schools)
		province_leads = len(student_ids_by_province.get(province_name, set())) if students_available else None
		highlights = []
		for school in schools:
			snapshot = latest.get(school.get("name")) or {}
			school_leads = len(student_ids_by_school.get(school.get("name"), set())) if students_available else None
			ward = ward_by_name.get(school.get("ward"), {})
			external_id = None
			school_code = str(school.get("school_code") or "").strip()
			if province_code and ward.get("ward_code") and school_code.isdigit():
				external_id = f"{province_code}-{ward['ward_code']}-{school_code.zfill(3)}"
			highlights.append({
				"id": external_id,
				"directoryId": external_id,
				"name": school.get("school_name"),
				"district": ward.get("ward_name"),
				"tier": school.get("school_tier"),
				"potentialScore": None,
				"grade12Students": None,
				"prospects": school_leads,
				"penetrationRate": None,
				"applications": snapshot.get("applicant_count"),
				"enrollmentForecast": snapshot.get("forecast_count"),
				"conversionRate": snapshot.get("conversion_rate"),
				"lastActivity": None,
				"recommendation": None,
				"nextAction": None,
				"classification": "Trọng điểm" if school.get("is_key_account") else None,
			})
		highlights.sort(
			key=lambda row: (
				row.get("applications") is None,
				-(row.get("applications") or 0),
				str(row.get("id") or ""),
				str(row.get("name") or ""),
			)
		)
		provinces.append({
			"code": province_code,
			"name": province.get("province_name") or province_name,
			"fullName": province.get("province_name") or province_name,
			"regionKey": region_key,
			"opportunity": None,
			"leads": province_leads,
			"conversion": _ratio(enrolled, applicants),
			"competition": None,
			"revenue": None,
			"grade12Population": None,
			"penetrationRate": None,
			"trend": None,
			"recommendation": None,
			"keyAction": None,
			"schoolCount": len(schools),
			"highSchools": highlights[:school_limit] if include_schools else [],
		})

	conversions = [row["conversion"] for row in provinces if row["conversion"] is not None]
	missing_support = set()
	if sources.get("schools") and not sources.get("snapshots"):
		missing_support.add("snapshots")
	if any(school.get("ward") for school in sources.get("schools", [])) and not sources.get("wards"):
		missing_support.add("wards")
	status = "partial" if failed or missing_support else "available"
	return {
		"status": status,
		"data": {
			"totalProvinces": len(provinces),
			"totalSchools": sum(row["schoolCount"] for row in provinces),
			"provinces": provinces,
			"regionSummary": {
				"scope": region,
				"count": len(provinces),
				"totalGrade12": sum(row["grade12Population"] for row in provinces if row["grade12Population"] is not None) or None,
				"totalLeads": sum(row["leads"] for row in provinces) if students_available else None,
				"avgConversion": round(sum(conversions) / len(conversions), 2) if conversions else None,
				"hotspotCount": None,
				"totalRevenue": None,
				"grade12Trend": None,
				"leadsTrend": None,
				"revenueTrend": None,
			},
			"metricConfig": {"key": metric, "label": None, "unit": None, "min": None, "max": None},
			"dataAvailability": {
				"opportunity": "unavailable",
				"competition": "unavailable",
				"revenue": "unavailable",
				"grade12Population": "unavailable",
			},
		},
		"dataAvailability": {
			"sections": {
				"identity": "available",
				"students": "unavailable" if "students" in failed else "available",
				"snapshots": "unavailable" if "snapshots" in failed or "snapshots" in missing_support else "available",
				"wards": "unavailable" if "wards" in failed or "wards" in missing_support else "available",
			},
			"fields": {
				"provinces[].opportunity": "unavailable",
				"provinces[].competition": "unavailable",
				"provinces[].revenue": "unavailable",
				"provinces[].grade12Population": "unavailable",
				"provinces[].recommendation": "unavailable",
			},
		},
		"meta": {
			"admissionYear": int(admission_year),
			"period": "30d",
			"region": region,
			"metric": metric,
			"asOf": _latest_as_of(sources.get("snapshots", [])),
			"scope": "director",
			"sourceDataRevision": _source_revision(sources),
		},
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_market_intelligence_overview(
	admissionYear=None,
	period="30d",
	region="all",
	metric="opportunity",
	includeSchools=True,
	schoolLimit=5,
):
	admission_year = resolve_admission_year(admissionYear)
	period = parse_enum(period, field="period", allowed={"30d"}, default="30d")
	region = parse_enum(region, field="region", allowed=REGIONS, default="all")
	metric = parse_enum(metric, field="metric", allowed=METRICS, default="opportunity")
	include_schools = parse_boolean(includeSchools, field="includeSchools", default=True)
	school_limit = parse_limit(schoolLimit, field="schoolLimit", minimum=1, maximum=20, default=5)
	try:
		sources, failed = _load_sources(admission_year)
	except MarketPrimarySourceUnavailable:
		raise_api_error("MARKET_DATA_UNAVAILABLE", "Không thể tải nguồn dữ liệu thị trường chính.", frappe.ValidationError, 503)
	return _build_overview(
		sources,
		failed,
		admission_year=admission_year,
		region=region,
		metric=metric,
		include_schools=include_schools,
		school_limit=school_limit,
	)
