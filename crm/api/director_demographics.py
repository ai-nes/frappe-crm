"""Aggregate-only demographics projections for the Director dashboard."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

import frappe
from frappe import _

from crm.api.director_students import (
	_as_iso,
	_fold,
	_resolve_admission_year,
	_table_exists,
)

MIN_SAMPLE_SIZE = 30
PERIOD_MONTHS = {"6m": 6, "12m": 12, "season": 12}
INTEREST_BUCKETS = (
	("ai", "AI", ("tri tue nhan tao", "artificial intelligence", "machine learning")),
	("software", "Phần mềm", ("phan mem", "software", "lap trinh", "cong nghe thong tin")),
	("business", "Kinh doanh", ("kinh doanh", "quan tri", "business", "marketing", "tai chinh")),
	("design", "Thiết kế", ("thiet ke", "design", "my thuat", "truyen thong")),
)
STUDENT_FIELDS = [
	"name",
	"gender",
	"current_grade",
	"study_stage",
	"major",
	"aspiration",
	"province",
	"high_school",
	"processing_status",
	"resolution",
	"admission_year",
	"creation",
]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_demographics_overview(
	admissionYear: str | int | None = None,
	period: str = "6m",
	scope: str = "all",
	page: str | int | None = 1,
	pageSize: str | int | None = 5,
) -> dict[str, Any]:
	"""Return aggregate demographics data without exposing student identity."""
	period = _normalize_period(period)
	scope = _normalize_scope(scope)
	page, page_size = _normalize_pagination(page, pageSize)
	resolved_year = _resolve_admission_year(admissionYear)
	rows = _load_students(resolved_year)
	lookups = _load_lookups(rows)
	evidence = _load_evidence([row.get("name") for row in rows if row.get("name")])
	records = [
		_enrich_student(row, lookups, evidence.get(row.get("name"), {}))
		for row in rows
		if row.get("name")
	]
	windows = _month_windows(period)
	all_segments = _build_segments(records, windows)
	segments, pagination = _paginate_segments(all_segments, page, page_size)
	year_number = _year_number(resolved_year)

	return {
		"data": {
			"kpis": _build_kpis(records, windows),
			"demand": _build_demand(records, windows),
			"audienceComposition": _build_audience_composition(records),
			"segments": segments,
			"acquisitionMap": _empty_acquisition_map(),
			"regionOpportunities": _build_region_opportunities(records),
			"regionalDemand": _build_regional_demand(records),
			"dataCoverage": _build_data_coverage(records),
		},
		"meta": {
			"admissionYear": year_number,
			"period": period,
			"scope": scope,
			"asOf": _as_iso(frappe.utils.now_datetime()),
			"totalProspects": len(records),
			"minSampleSize": MIN_SAMPLE_SIZE,
			**pagination,
			"dataAvailability": {
				"trend": any(record.get("created_at") for record in records),
				"tuition": False,
				"revenue": False,
				"eligibleSegments": len(all_segments),
				"acquisitionMap": "unavailable",
			},
		},
	}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_director_demographics_segment(
	segment_id: str | None = None,
	admissionYear: str | int | None = None,
) -> dict[str, Any]:
	"""Return one aggregate segment and its benchmark without personal data."""
	if not str(segment_id or "").strip():
		_raise_api_error("INVALID_SEGMENT_ID", "segmentId không được để trống.", frappe.ValidationError, 400)

	resolved_year = _resolve_admission_year(admissionYear)
	rows = _load_students(resolved_year)
	lookups = _load_lookups(rows)
	evidence = _load_evidence([row.get("name") for row in rows if row.get("name")])
	records = [
		_enrich_student(row, lookups, evidence.get(row.get("name"), {}))
		for row in rows
		if row.get("name")
	]
	windows = _month_windows("6m")
	segments = _build_segments(records, windows)
	segment = next((item for item in segments if item["id"] == segment_id), None)
	if not segment:
		_raise_api_error(
			"SEGMENT_NOT_FOUND",
			"Không tìm thấy phân khúc hoặc phân khúc chưa đủ dữ liệu.",
			frappe.DoesNotExistError,
			404,
		)

	benchmark = _benchmark_segment(segment, segments)
	region_opportunities = _build_region_opportunities(records, selected_region=segment["region"])
	return {
		"data": {
			"segment": segment,
			"benchmark": benchmark,
			"regionOpportunities": region_opportunities,
			"nextAction": _build_next_action(segment),
			"guardrails": _guardrails(),
		},
		"meta": {
			"admissionYear": _year_number(resolved_year),
			"asOf": _as_iso(frappe.utils.now_datetime()),
			"minSampleSize": MIN_SAMPLE_SIZE,
			"sampleSize": segment["prospects"],
		},
	}


def _normalize_period(value: str | None) -> str:
	period = str(value or "6m").strip().lower()
	if period not in PERIOD_MONTHS:
		_raise_api_error("INVALID_PERIOD", "period phải là 6m, 12m hoặc season.", frappe.ValidationError, 400)
	return period


def _normalize_scope(value: str | None) -> str:
	scope = str(value or "all").strip().lower()
	if scope != "all":
		_raise_api_error("INVALID_SCOPE", "scope hiện chỉ hỗ trợ all.", frappe.ValidationError, 400)
	return scope


def _normalize_pagination(page: str | int | None, page_size: str | int | None) -> tuple[int, int]:
	"""Validate the one-based page and bounded page size accepted by the API."""
	page_number = _parse_positive_integer(page, "page")
	page_size_number = _parse_positive_integer(page_size, "pageSize")
	if page_size_number > 100:
		_raise_api_error(
			"INVALID_PAGINATION",
			"pageSize phải là số nguyên trong khoảng 1..100.",
			frappe.ValidationError,
			400,
		)
	return page_number, page_size_number


def _parse_positive_integer(value: str | int | None, field_name: str) -> int:
	normalized_value = str(value or "").strip()
	if isinstance(value, bool) or not re.fullmatch(r"[1-9]\d*", normalized_value):
		_raise_api_error(
			"INVALID_PAGINATION",
			f"{field_name} phải là số nguyên dương.",
			frappe.ValidationError,
			400,
		)
	try:
		return int(normalized_value)
	except ValueError:
		_raise_api_error(
			"INVALID_PAGINATION",
			f"{field_name} phải là số nguyên dương.",
			frappe.ValidationError,
			400,
		)
		raise AssertionError("_raise_api_error must raise")


def _paginate_segments(segments: list[dict[str, Any]], page: int, page_size: int) -> tuple[list[dict[str, Any]], dict[str, int | bool]]:
	"""Slice already-sorted segments and return the required pagination metadata."""
	total = len(segments)
	total_pages = max(1, (total + page_size - 1) // page_size)
	if page > total_pages:
		_raise_api_error(
			"INVALID_PAGINATION",
			"page vượt quá số trang hiện có.",
			frappe.ValidationError,
			400,
		)
	start = (page - 1) * page_size
	return segments[start : start + page_size], {
		"page": page,
		"pageSize": page_size,
		"total": total,
		"totalPages": total_pages,
		"hasNextPage": page < total_pages,
	}


def _empty_acquisition_map() -> dict[str, Any]:
	"""Return the complete Acquisition Map contract without fabricating unavailable metrics."""
	return {
		"attributionModel": {"firstTouch": "first-touch", "lastTouch": "last-touch"},
		"platformLeadCost": [],
		"leadTrendComparison": [],
		"dailySpendLeads": [],
		"touchpointPlatformMatrix": {"columns": [], "rows": []},
		"budgetByPlatformRole": [],
		"formFunnel": [],
		"formCompletion": [],
		"formDropoffByField": [],
		"captureModeComparison": [],
		"leadQualityBySource": [],
		"validLeadRateTrend": [],
		"handoffDataCompleteness": [],
		"identityMatchBreakdown": [],
		"firstTouchBySource": [],
		"lastTouchBySource": [],
		"firstVsLastSource": [],
		"attributionFlow": [],
		"cohortEnrollmentMatrix": [],
		"enrollmentLagHistogram": {"medianDays": None, "buckets": []},
		"cumulativeConversion": [],
		"firstContactLatency": [],
		"submissionTiming": {
			"weekdays": [],
			"hours": [],
			"values": [],
			"timezone": "Asia/Ho_Chi_Minh",
		},
		"handoffSuccessBySource": [],
		"costPerEnrolledBySource": [],
	}


def _load_students(admission_year: str) -> list:
	return frappe.get_all(
		"CRM Lead",
		filters={"admission_year": admission_year},
		fields=STUDENT_FIELDS,
		order_by="creation asc, name asc",
		limit_page_length=0,
	)


def _load_lookups(rows: list) -> dict[str, dict]:
	major_ids = {row.get("major") for row in rows if row.get("major")}
	province_ids = {row.get("province") for row in rows if row.get("province")}
	school_ids = {row.get("high_school") for row in rows if row.get("high_school")}
	term_ids = set()

	majors = {}
	if major_ids and _table_exists("CRM Major"):
		major_rows = frappe.get_all(
			"CRM Major",
			filters={"name": ["in", list(major_ids)]},
			fields=["name", "major_name", "major_group"],
			limit_page_length=0,
		)
		majors = {
			row.get("name"): {"label": row.get("major_name") or row.get("name"), "group": row.get("major_group")}
			for row in major_rows
		}
		term_ids.update(row.get("major_group") for row in major_rows if row.get("major_group"))

	provinces = {}
	if province_ids and _table_exists("CRM Province"):
		province_rows = frappe.get_all(
			"CRM Province",
			filters={"name": ["in", list(province_ids)]},
			fields=["name", "province_name", "province_code", "region"],
			limit_page_length=0,
		)
		provinces = {
			row.get("name"): {
				"label": row.get("province_name") or row.get("province_code") or row.get("name"),
				"region": row.get("region"),
			}
			for row in province_rows
		}
		term_ids.update(row.get("region") for row in province_rows if row.get("region"))

	schools = {}
	if school_ids and _table_exists("CRM High School"):
		school_rows = frappe.get_all(
			"CRM High School",
			filters={"name": ["in", list(school_ids)]},
			fields=["name", "school_name", "school_type"],
			limit_page_length=0,
		)
		schools = {
			row.get("name"): {"label": row.get("school_name") or row.get("name"), "type": row.get("school_type")}
			for row in school_rows
		}
		term_ids.update(row.get("school_type") for row in school_rows if row.get("school_type"))

	regions = {}
	if term_ids:
		term_id_list = list(term_ids)
		for lookup_doctype in ("CRM Region", "CRM Major Group", "CRM School Type"):
			if not _table_exists(lookup_doctype):
				continue
			for row in frappe.get_all(
				lookup_doctype,
				filters={"name": ["in", term_id_list]},
				fields=["name", "display_name"],
				limit_page_length=0,
			):
				regions[row.get("name")] = row.get("display_name") or row.get("name")

	return {"majors": majors, "provinces": provinces, "schools": schools, "regions": regions}


def _load_evidence(student_ids: list[str]) -> dict[str, dict[str, Any]]:
	evidence = {
		student_id: {"interactions": [], "assessment": {}, "applications": []} for student_id in student_ids
	}
	if not student_ids:
		return evidence

	if _table_exists("CRM Interaction"):
		for row in frappe.get_all(
			"CRM Interaction",
			filters={"student": ["in", student_ids]},
			fields=["student", "channel", "interaction_datetime", "creation"],
			order_by="interaction_datetime desc, creation desc",
			limit_page_length=0,
		):
			evidence.setdefault(row.get("student"), {"interactions": [], "assessment": {}, "applications": []})[
				"interactions"
			].append(row)

	if _table_exists("CRM Student Assessment"):
		assessment_rows = frappe.get_all(
			"CRM Student Assessment",
			filters={"student": ["in", student_ids]},
			fields=["student", "status", "interest", "signal_score", "enrollment_probability", "assessed_at", "creation"],
			order_by="assessed_at desc, creation desc",
			limit_page_length=0,
		)
		for row in assessment_rows:
			student_evidence = evidence.setdefault(
				row.get("student"), {"interactions": [], "assessment": {}, "applications": []}
			)
			if not student_evidence["assessment"]:
				student_evidence["assessment"] = row

	if _table_exists("CRM Admission Application"):
		for row in frappe.get_all(
			"CRM Admission Application",
			filters={"student": ["in", student_ids]},
			fields=["student", "status", "submitted_at", "enrolled_at", "creation"],
			limit_page_length=0,
		):
			evidence.setdefault(row.get("student"), {"interactions": [], "assessment": {}, "applications": []})[
				"applications"
			].append(row)

	return evidence


def _enrich_student(row, lookups: dict[str, dict], evidence: dict[str, Any]) -> dict[str, Any]:
	major = lookups.get("majors", {}).get(row.get("major"), {})
	province = lookups.get("provinces", {}).get(row.get("province"), {})
	school = lookups.get("schools", {}).get(row.get("high_school"), {})
	region_id = province.get("region")
	region_label = lookups.get("regions", {}).get(region_id) or region_id or "Không xác định"
	major_label = major.get("label") or row.get("major") or ""
	major_group = lookups.get("regions", {}).get(major.get("group")) or major.get("group") or ""
	aspiration = row.get("aspiration") or ""
	interest = _interest_bucket(major_label, major_group, aspiration)
	interactions = evidence.get("interactions", [])
	applications = evidence.get("applications", [])
	assessment = evidence.get("assessment") or {}
	processing_status = _normalize_text(row.get("processing_status"))
	resolution = _normalize_text(row.get("resolution"))
	application_statuses = {_normalize_text(item.get("status")) for item in applications}
	qualified = assessment.get("status") == "confirmed" or bool(
		application_statuses.intersection({"submitted", "under review", "accepted", "enrolled"})
	)
	enrolled = resolution == "created" or "enrolled" in application_statuses
	counselling = processing_status in {"processing", "assigned"}

	return {
		"gender_id": _gender_id(row.get("gender")),
		"gender_label": row.get("gender") or "Chưa xác định",
		"grade_id": _grade_id(row),
		"grade_label": _grade_label(row),
		"interest": interest,
		"province_id": row.get("province"),
		"province_label": province.get("label") or row.get("province") or "Không xác định",
		"region_id": region_id,
		"region_label": region_label,
		"school_type": school.get("type"),
		"has_interest": bool(row.get("major") or row.get("aspiration")),
		"created_at": _coerce_datetime(row.get("creation")),
		"engaged": bool(interactions),
		"qualified": qualified,
		"counselling": counselling,
		"applications": bool(applications),
		"enrolled": enrolled,
		"interactions": interactions,
	}


def _interest_bucket(major: str, major_group: str, aspiration: str) -> dict[str, str]:
	value = _normalize_text(" ".join(str(item or "") for item in (major, major_group, aspiration)))
	for bucket_id, label, keywords in INTEREST_BUCKETS:
		if any(keyword in value for keyword in keywords) or (bucket_id == "ai" and re.search(r"\bai\b", value)):
			return {"id": bucket_id, "label": label}
	return {"id": "other", "label": "Khác"}


def _build_kpis(records: list[dict[str, Any]], windows: list[tuple[str, datetime, datetime]]) -> list[dict[str, Any]]:
	current_start = windows[0][1]
	current_end = windows[-1][2]
	previous_start = _shift_month(current_start, -len(windows))
	previous_end = current_start
	metrics = [
		("prospects", "Tổng hồ sơ", lambda record: True, "primary"),
		("engaged", "Đã tương tác", lambda record: record["engaged"], "info"),
		("qualified", "Đủ điều kiện tư vấn", lambda record: record["qualified"], "success"),
		("enrolled", "Đã nhập học", lambda record: record["enrolled"], "warning"),
	]
	result = []
	for metric_id, label, predicate, tone in metrics:
		value = sum(predicate(record) for record in records)
		current = sum(predicate(record) and _in_range(record.get("created_at"), current_start, current_end) for record in records)
		previous = sum(predicate(record) and _in_range(record.get("created_at"), previous_start, previous_end) for record in records)
		progress = _metric_progress(metric_id, value, records)
		helper = {
			"prospects": "Tổng dữ liệu kỳ tuyển sinh",
			"engaged": f"{_percentage(value, len(records))}% tổng hồ sơ" if records else "0% tổng hồ sơ",
			"qualified": f"{_percentage(value, sum(record['engaged'] for record in records))}% từ engaged"
			if any(record["engaged"] for record in records)
			else "Chưa có dữ liệu engaged",
			"enrolled": f"{_percentage(value, len(records))}% tổng hồ sơ" if records else "0% tổng hồ sơ",
		}[metric_id]
		result.append(
			{
				"id": metric_id,
				"label": label,
				"value": _format_number(value),
				"change": _format_change(current, previous),
				"helper": helper,
				"progress": progress,
				"tone": tone,
			}
		)
	return result


def _build_demand(records: list[dict[str, Any]], windows: list[tuple[str, datetime, datetime]]) -> dict[str, list]:
	trend = []
	for index, (label, start, end) in enumerate(windows):
		bucket = {"month": label}
		for interest_id, _, _ in INTEREST_BUCKETS:
			bucket[interest_id] = sum(
				record["interest"]["id"] == interest_id and _in_range(record.get("created_at"), start, end)
				for record in records
			)
		trend.append(bucket)

	latest = trend[-1] if trend else {}
	previous = trend[-2] if len(trend) > 1 else {}
	summary = []
	for interest_id, label, _ in INTEREST_BUCKETS:
		value = latest.get(interest_id, 0)
		summary.append(
			{
				"id": interest_id,
				"label": label,
				"value": value,
				"change": _percent_change(value, previous.get(interest_id, 0)),
			}
		)
	return {"trend": trend, "summary": summary}


def _build_audience_composition(records: list[dict[str, Any]]) -> dict[str, Any]:
	total = len(records)
	gender_counts = Counter(record["gender_label"] for record in records)
	gender_ids = {"Nữ": "female", "Nam": "male", "Chưa xác định": "unknown"}
	gender = [
		{
			"id": gender_ids.get(label, _slug(label)),
			"name": label,
			"value": _percentage(count, total),
		}
		for label, count in sorted(gender_counts.items())
	]
	profile_specs = [
		("grade-12", "Học sinh lớp 12", lambda record: record["grade_id"] == "grade-12"),
		("has-interest", "Đã có ngành quan tâm", lambda record: record["has_interest"]),
	]
	if any(record.get("school_type") for record in records):
		profile_specs.insert(1, ("public-school", "Trường công lập", lambda record: _is_public_school(record["school_type"])))
	profiles = []
	for profile_id, label, predicate in profile_specs:
		count = sum(predicate(record) for record in records)
		profiles.append({"id": profile_id, "label": label, "value": _percentage(count, total), "count": count})
	return {"total": total, "gender": gender, "profiles": profiles}


def _build_segments(records: list[dict[str, Any]], windows: list[tuple[str, datetime, datetime]]) -> list[dict[str, Any]]:
	groups = defaultdict(list)
	for record in records:
		region_key = record["province_id"] or record["region_id"] or "unknown"
		groups[(record["gender_id"], record["interest"]["id"], region_key)].append(record)
	eligible = [group for group in groups.values() if len(group) >= MIN_SAMPLE_SIZE]
	max_size = max((len(group) for group in eligible), default=0)
	segments = []
	for group in eligible:
		first = group[0]
		interest = first["interest"]
		region = first["province_label"] if first["province_id"] else first["region_label"]
		gender_id = first["gender_id"]
		grade = _dominant(group, "grade_label", "Không xác định")
		segment_id = _slug(f"{gender_id}-{interest['id']}-{region}")
		benchmark_records = [record for record in records if record["interest"]["id"] == interest["id"]]
		segments.append(
			_build_segment(
				segment_id,
				group,
				benchmark_records,
				windows,
				max_size,
				gender_id,
				grade,
				region,
			)
		)
	segments.sort(key=lambda segment: (-segment["opportunityScore"], segment["id"]))
	return segments


def _build_segment(
	segment_id: str,
	group: list[dict[str, Any]],
	benchmark_records: list[dict[str, Any]],
	windows: list[tuple[str, datetime, datetime]],
	max_size: int,
	gender_id: str,
	grade: str,
	region: str,
) -> dict[str, Any]:
	first = group[0]
	interest = first["interest"]
	prospects = len(group)
	engaged = sum(record["engaged"] for record in group)
	qualified = sum(record["qualified"] for record in group)
	counselling = sum(record["counselling"] for record in group)
	applications = sum(record["applications"] for record in group)
	enrolled = sum(record["enrolled"] for record in group)
	monthly = []
	for label, start, end in windows:
		monthly.append(
			{
				"month": label,
				"current": sum(_in_range(record.get("created_at"), start, end) for record in group),
				"benchmark": sum(_in_range(record.get("created_at"), start, end) for record in benchmark_records),
			}
		)
	previous = monthly[-2]["current"] if len(monthly) > 1 else 0
	latest = monthly[-1]["current"] if monthly else 0
	opportunity_score = round(100 * prospects / max_size) if max_size else 0
	return {
		"id": segment_id,
		"name": f"{first['gender_label']} · {grade} · {region} · quan tâm {interest['label']}",
		"shortName": f"{first['gender_label']} · {interest['label']}",
		"description": f"{_format_number(prospects)} hồ sơ, {_percentage(engaged, prospects)}% đã có tương tác.",
		"region": region,
		"interest": interest["label"],
		"prospects": prospects,
		"engaged": engaged,
		"qualified": qualified,
		"counselling": counselling,
		"applications": applications,
		"enrolled": enrolled,
		"conversion": _percentage(enrolled, prospects),
		"tuition": None,
		"revenue": None,
		"growth": _percent_change(latest, previous),
		"coverage": _percentage(engaged, prospects),
		"opportunityScore": opportunity_score,
		"tone": _tone(opportunity_score),
		"filters": [
			{"id": "gender", "label": "Giới tính", "value": first["gender_label"]},
			{"id": "grade", "label": "Khối lớp", "value": grade},
			{"id": "interest", "label": "Quan tâm", "value": interest["label"]},
			{"id": "province" if first["province_id"] else "region", "label": "Tỉnh/TP" if first["province_id"] else "Vùng", "value": region},
		],
		"channels": _channel_distribution(group),
		"monthlyProspects": monthly,
	}


def _build_region_opportunities(records: list[dict[str, Any]], selected_region: str | None = None) -> list[dict[str, Any]]:
	counts = Counter(record["province_label"] for record in records if record["province_id"])
	max_count = max(counts.values(), default=0)
	items = []
	for rank, (name, count) in enumerate(counts.most_common(5), start=1):
		items.append(
			{
				"rank": rank,
				"name": name,
				"score": round(100 * count / max_count) if max_count else 0,
				"selected": name == selected_region if selected_region else False,
			}
		)
	return items


def _build_regional_demand(records: list[dict[str, Any]]) -> dict[str, list]:
	region_counts = Counter(record["province_label"] for record in records if record["province_id"])
	regions = [name for name, _ in region_counts.most_common(5)]
	columns = [{"id": _slug(name), "name": name} for name in regions]
	rows = []
	for interest_id, label, _ in INTEREST_BUCKETS:
		counts = {
			_slug(region): sum(
				record["interest"]["id"] == interest_id and record["province_label"] == region
				for record in records
			)
			for region in regions
		}
		max_count = max(counts.values(), default=0)
		rows.append(
			{
				"interest": label,
				"scores": {
					region_id: round(100 * count / max_count) if max_count else 0
					for region_id, count in counts.items()
				},
			}
		)
	return {"columns": columns, "rows": rows}


def _build_data_coverage(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
	total = len(records)
	student_info_fields = sum(
		bool(record["gender_id"] != "unknown") + bool(record["grade_id"] != "unknown") for record in records
	)
	return [
		{"label": "Địa lý", "detail": "Tỉnh, huyện, vùng tuyển sinh", "value": _percentage(sum(bool(record["province_id"]) for record in records), total), "tone": "success"},
		{"label": "Thông tin học sinh", "detail": "Giới tính, khối lớp", "value": _percentage(student_info_fields, total * 2), "tone": "success" if student_info_fields else "warning"},
		{"label": "Ngành quan tâm", "detail": "Nhóm ngành và ngành cụ thể", "value": _percentage(sum(record["has_interest"] for record in records), total), "tone": "success"},
		{"label": "Hành vi", "detail": "Tương tác CRM", "value": _percentage(sum(record["engaged"] for record in records), total), "tone": "success" if any(record["engaged"] for record in records) else "warning"},
		{"label": "Thông tin học phí", "detail": "Chưa có nguồn dữ liệu canonical", "value": 0, "tone": "danger"},
	]


def _benchmark_segment(segment: dict[str, Any], segments: list[dict[str, Any]]) -> dict[str, Any]:
	candidates = [
		item
		for item in segments
		if item["id"] != segment["id"] and item["interest"] == segment["interest"] and item["region"] == segment["region"]
	]
	return max(candidates, key=lambda item: item["prospects"], default=segment)


def _build_next_action(segment: dict[str, Any]) -> dict[str, Any]:
	channels = segment.get("channels") or []
	top_channel = channels[0]["name"] if channels else "kênh có consent hợp lệ"
	priority = "high" if segment["opportunityScore"] >= 85 else "normal"
	growth = segment.get("growth")
	growth_text = f"{growth:+.1f}%" if growth is not None else "chưa đủ dữ liệu tăng trưởng"
	return {
		"priority": priority,
		"label": "Ưu tiên cao" if priority == "high" else "Theo dõi",
		"title": "Ưu tiên tiếp cận sớm" if priority == "high" else "Theo dõi thêm dữ liệu",
		"description": f"Nhóm có {_format_number(segment['prospects'])} hồ sơ và {growth_text} tăng trưởng kỳ gần nhất.",
		"steps": [
			{"order": 1, "title": f"Tiếp cận qua {top_channel}", "detail": "Chỉ sử dụng kênh đã có consent phù hợp."},
			{"order": 2, "title": "Đo lường tương tác", "detail": "Theo dõi engaged, qualified và applications theo cùng kỳ."},
			{"order": 3, "title": "Đánh giá lại sau 30 ngày", "detail": "Không suy luận thuộc tính nhạy cảm từ phân khúc."},
		],
	}


def _guardrails() -> list[dict[str, str]]:
	return [
		{
			"criterion": "Khả năng học phí",
			"issue": "Không suy đoán thu nhập gia đình của người chưa thành niên.",
			"replacement": "Dùng hành vi xem học phí và yêu cầu hỗ trợ đã có consent.",
			"status": "Tạm khóa",
			"tone": "error",
		}
	]


def _channel_distribution(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
	channels = Counter(
		str(interaction.get("channel") or "Không xác định")
		for record in records
		for interaction in record["interactions"]
	)
	total = sum(channels.values())
	return [{"name": name, "value": _percentage(count, total)} for name, count in channels.most_common()]


def _metric_progress(metric_id: str, value: int, records: list[dict[str, Any]]) -> float:
	if not records:
		return 0
	if metric_id == "engaged":
		return _percentage(value, len(records))
	if metric_id == "qualified":
		return _percentage(value, sum(record["engaged"] for record in records))
	return _percentage(value, len(records))


def _percentage(numerator: int | float, denominator: int | float) -> float:
	return round(100 * numerator / denominator, 1) if denominator else 0.0


def _percent_change(current: int | float, previous: int | float) -> float | None:
	return round(100 * (current - previous) / previous, 1) if previous else None


def _format_change(current: int | float, previous: int | float) -> str:
	change = _percent_change(current, previous)
	return f"{change:+.1f}%" if change is not None else "—"


def _format_number(value: int | float) -> str:
	return f"{int(value):,}".replace(",", ".")


def _tone(score: int) -> str:
	if score >= 85:
		return "primary"
	if score >= 70:
		return "info"
	if score >= 55:
		return "success"
	return "warning"


def _dominant(records: list[dict[str, Any]], field: str, default: str) -> str:
	values = [record.get(field) for record in records if record.get(field)]
	return Counter(values).most_common(1)[0][0] if values else default


def _gender_id(value: str | None) -> str:
	return {"nữ": "female", "nam": "male"}.get(_normalize_text(value), "unknown")


def _grade_id(row) -> str:
	grade = str(row.get("current_grade") or "").strip()
	if grade in {"10", "11", "12"}:
		return f"grade-{grade}"
	if row.get("study_stage"):
		return _slug(row.get("study_stage"))
	return "unknown"


def _grade_label(row) -> str:
	grade = str(row.get("current_grade") or "").strip()
	if grade in {"10", "11", "12"}:
		return f"Lớp {grade}"
	if row.get("study_stage"):
		return str(row.get("study_stage"))
	return "Không xác định"


def _is_public_school(value: str | None) -> bool:
	return any(token in _normalize_text(value) for token in ("cong lap", "public"))


def _coerce_datetime(value) -> datetime | None:
	if not value:
		return None
	try:
		return frappe.utils.get_datetime(value)
	except (AttributeError, TypeError, ValueError):
		return None


def _month_windows(period: str) -> list[tuple[str, datetime, datetime]]:
	now = _coerce_datetime(frappe.utils.now_datetime()) or datetime.now()
	first = datetime(now.year, now.month, 1)
	months = PERIOD_MONTHS[period]
	start = _shift_month(first, -(months - 1))
	return [
		(
			f"T{index + 1}",
			window_start,
			_shift_month(window_start, 1),
		)
		for index, window_start in enumerate(_month_starts(start, months))
	]


def _month_starts(start: datetime, count: int) -> list[datetime]:
	return [_shift_month(start, offset) for offset in range(count)]


def _shift_month(value: datetime, offset: int) -> datetime:
	month_index = value.year * 12 + value.month - 1 + offset
	year, month_index = divmod(month_index, 12)
	return value.replace(year=year, month=month_index + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _in_range(value: datetime | None, start: datetime, end: datetime) -> bool:
	return bool(value and start <= value < end)


def _year_number(value: str | int) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		year_name = frappe.db.get_value("CRM Admission Year", value, "year_name")
		try:
			return int(year_name)
		except (TypeError, ValueError):
			return 0


def _slug(value: Any) -> str:
	return re.sub(r"[^a-z0-9]+", "-", _normalize_text(value)).strip("-")


def _normalize_text(value: Any) -> str:
	return _fold(value).replace("đ", "d").replace("Đ", "d")


def _raise_api_error(code: str, message: str, exception, status: int) -> None:
	if getattr(frappe, "local", None) and isinstance(getattr(frappe.local, "response", None), dict):
		frappe.local.response["error"] = {"code": code, "message": message}
		frappe.local.response["http_status_code"] = status
	frappe.throw(_(message), exception)
