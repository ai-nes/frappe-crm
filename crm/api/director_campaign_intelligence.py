"""Campaign intelligence snapshot for the Director dashboard."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import frappe

from crm.api.director_school_common import parse_limit, raise_api_error, resolve_admission_year
from crm.fcrm.role_policy import (
	CANONICAL_PROFILE_ROLES,
	DESK_MANAGEMENT_ROLE_NAMES,
	FRAMEWORK_ROLE_NAMES,
	LEGACY_OVERLAY_ROLES,
	LEGACY_UNMAPPED_ROLES,
	ROLE_BACKFILL_SOURCES,
	classify_role_set,
	resolve_crm_profile,
)

LOCAL_TIMEZONE = ZoneInfo("Asia/Ho_Chi_Minh")
GRANULARITIES = frozenset({"day", "week", "month"})
LEAD_STATUS_GROUPS = {
	"new": "Mới",
	"in_progress": "Đang xử lý",
	"no_response": "Chưa kết nối",
	"disqualified": "Không phù hợp",
	"converted": "Đã chuyển đổi",
}
LEAD_QUALITY_GROUPS = {"invalid": "Sai số", "duplicate": "Lead trùng", "unknown": "Chưa phân loại"}
PRIMARY_ATTRIBUTION_RULE = "first_touch_weight_confidence_earliest_v1"
LEAD_STATUS_ALIASES = {
	"new": {"NEW"},
	"in_progress": {"PROCESSING", "PROCESSED", "ASSIGNED"},
	"converted": {"CREATED"},
	"disqualified": {"INVALID", "SPAM", "FAILED"},
	"duplicate": {"DUPLICATE"},
}
FUNNEL_STAGES = (
	("impressions", "Impressions"),
	("clicks", "Clicks"),
	("landingVisits", "Landing visits"),
	("leads", "Leads"),
	("qualified", "Qualified"),
	("applications", "Applications"),
	("enrollments", "Enrollments"),
)
FACT_FIELDS = [
	"name",
	"campaign",
	"channel_assignment",
	"period_start",
	"period_end",
	"spend",
	"impressions",
	"clicks",
	"leads",
	"applications",
	"enrolled",
	"raw_measures",
	"dimension_values",
]


@frappe.whitelist(methods=["GET"])
def get_director_campaign_intelligence(
	admissionYear: str | int | None = None,
	granularity: str = "week",
	channel: str = "all",
	campus: str = "all",
	scope: str = "all",
	fromDate: str | None = None,
	toDate: str | None = None,
	**query: Any,
) -> dict[str, Any]:
	"""Return one permission-scoped, internally consistent campaign snapshot."""

	access = require_campaign_intelligence_access()
	admission_year = resolve_admission_year(admissionYear)
	date_from, date_to, warnings = _resolve_date_range(
		admission_year, query.get("from", fromDate), query.get("to", toDate)
	)
	selected_granularity = _parse_granularity(granularity)
	scope_context = _resolve_scope(scope, access)
	campus_id = _resolve_link_filter("campus", campus, "CRM Campus")
	channel_id = _resolve_link_filter("channel", channel, "CRM Platform")
	facts = _load_facts(date_from, date_to, campus_id, channel_id, scope_context, warnings)
	leads = _load_campaign_lead_rows(admission_year, date_from, date_to, campus_id, channel_id, scope_context)
	campaign_ids = {row["campaign"] for row in facts} | set(leads or {})
	campaigns = _load_campaigns(campaign_ids)
	attribution = _load_attribution(
		campaign_ids, date_from, date_to, warnings
	)
	return _build_response(
		admission_year,
		date_from,
		date_to,
		selected_granularity,
		scope_context,
		facts,
		campaigns,
		attribution,
		warnings,
		leads,
	)


@frappe.whitelist(methods=["GET"])
def get_campaign_leads(
	campaignId: str | None = None,
	admissionYear: str | int | None = None,
	statusGroup: str = "all",
	page: str | int = 1,
	pageSize: str | int = 20,
	channel: str = "all",
	campus: str = "all",
	scope: str = "all",
	fromDate: str | None = None,
	toDate: str | None = None,
	**query: Any,
) -> dict[str, Any]:
	"""Return minimal CRM Lead rows from the same primary-attribution cohort as the chart."""
	access = require_campaign_intelligence_access()
	year = resolve_admission_year(admissionYear)
	date_from, date_to, warnings = _resolve_date_range(year, query.get("from", fromDate), query.get("to", toDate))
	page_number = parse_limit(page, field="page", minimum=1, maximum=1000000, default=1)
	page_size = parse_limit(pageSize, field="pageSize", minimum=1, maximum=100, default=20)
	group = str(statusGroup or "all").strip().lower()
	if group not in {"all", *LEAD_STATUS_GROUPS, *LEAD_QUALITY_GROUPS}:
		raise_api_error("INVALID_QUERY", "Tham số statusGroup không hợp lệ.", frappe.ValidationError, 400)
	campaign_id = str(campaignId or "").strip()
	if not campaign_id or len(campaign_id) > 140:
		raise_api_error("INVALID_QUERY", "Tham số campaignId không hợp lệ.", frappe.ValidationError, 400)
	# Permission-aware lookup deliberately returns the same error for missing/invisible campaigns.
	if not frappe.get_list("CRM Campaign", filters={"name": campaign_id}, fields=["name"], limit_page_length=1):
		raise_api_error("NOT_FOUND", "Không tìm thấy chiến dịch trong phạm vi truy cập.", frappe.DoesNotExistError, 404)
	scope_context = _resolve_scope(scope, access)
	campus_id = _resolve_link_filter("campus", campus, "CRM Campus")
	channel_id = _resolve_link_filter("channel", channel, "CRM Platform")
	page_result = _load_campaign_lead_page(
		year,
		date_from,
		date_to,
		campus_id,
		channel_id,
		scope_context,
		campaign_id,
		group,
		page_number,
		page_size,
	)
	if page_result is None:
		raise_api_error(
			"CAMPAIGN_INTELLIGENCE_DATA_UNAVAILABLE",
			"Nguồn dữ liệu lead chưa sẵn sàng.",
			frappe.ValidationError,
			503,
		)
	rows = page_result["rows"]
	total = page_result["total"]
	return {
		"meta": {"admissionYear": int(year), "from": date_from.isoformat(), "to": date_to.isoformat(),
			"scope": scope_context["id"], "attributionRule": PRIMARY_ATTRIBUTION_RULE, "warnings": warnings},
		"campaignId": campaign_id,
		"items": _build_lead_items(rows),
		"pagination": {"page": page_number, "pageSize": page_size, "total": total,
			"totalPages": (total + page_size - 1) // page_size},
	}


def _primary_attributions(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
	"""Choose globally within the date cohort, before campus/channel/campaign filters."""
	def rank(row):
		return (-int(row.get("is_first_touch") or 0), -_number(row.get("weight")),
			-_number(row.get("confidence")), str(row.get("attributed_at") or ""), str(row["name"]))
	primary = {}
	for row in sorted(rows, key=rank):
		if row.get("student") and row.get("campaign"):
			primary.setdefault(row["student"], row)
	return primary


def _lead_status_group(code: str, status: dict[str, Any]) -> str:
	resolution = str(status.get("resolution") or code or "").upper()
	processing = str(status.get("processing_status") or "").upper()
	if resolution == "CREATED":
		return "converted"
	if resolution == "DUPLICATE":
		return "duplicate"
	if resolution in {"INVALID", "SPAM", "FAILED"}:
		return "disqualified"
	if processing == "NEW":
		return "new"
	if processing in LEAD_STATUS_ALIASES["in_progress"]:
		return "in_progress"
	return "unknown"


def _load_campaign_lead_rows(year, date_from, date_to, campus, channel, scope):
	"""Load one permission-scoped cohort; unavailable optional tables yield no lead metrics."""
	if not all(frappe.db.table_exists(doctype) for doctype in ("CRM Campaign Attribution", "CRM Lead")):
		return None
	attributions = frappe.get_all(
		"CRM Campaign Attribution",
		filters=[["attributed_at", ">=", date_from.isoformat()],
			["attributed_at", "<", (date_to + timedelta(days=1)).isoformat()]],
		fields=["name", "student", "campaign", "weight", "confidence", "is_first_touch", "attributed_at"],
		limit_page_length=0,
	)
	primary = _primary_attributions(attributions)
	if not primary:
		return {}
	campaign_ids = {row["campaign"] for row in primary.values()}
	visible_campaigns = set(campaign_ids)
	if campaign_ids:
		campaign_filters = {"name": ["in", sorted(campaign_ids)]}
		if campus:
			campaign_filters["campus"] = campus
		visible_campaigns = {
			row["name"]
			for row in frappe.get_list("CRM Campaign", filters=campaign_filters, fields=["name"], limit_page_length=0)
		}
	if channel:
		assignments = frappe.get_all(
			"CRM Campaign Channel Assignment",
			filters={"campaign": ["in", sorted(visible_campaigns)], "channel": channel}
			if visible_campaigns
			else {"campaign": ["in", [""]], "channel": channel},
			fields=["campaign"],
			limit_page_length=0,
		)
		visible_campaigns &= {row["campaign"] for row in assignments}
	student_ids = [student for student, row in primary.items() if row["campaign"] in visible_campaigns]
	if not student_ids:
		return {}
	year_id = frappe.db.get_value("CRM Admission Year", {"year_name": year}, "name") or year
	filters = {"name": ["in", student_ids], "admission_year": year_id}
	if campus:
		filters["branch"] = campus
	if scope.get("territory"):
		teams = frappe.get_all("CRM Team", filters={"territory": scope["territory"]}, pluck="name")
		filters["owning_team"] = ["in", teams or [""]]
	students = frappe.get_list("CRM Lead", filters=filters,
		fields=["name", "lead_code", "student_name", "high_school", "processing_status", "resolution", "owner_staff", "source", "modified"],
		limit_page_length=0)
	grouped = defaultdict(list)
	for student in students:
		row = dict(student)
		code = str(row.get("processing_status") or "")
		status = {"processing_status": code, "resolution": row.get("resolution")}
		row.update(statusCode=code, status=code or "Unknown",
			statusGroup=_lead_status_group(code, status))
		grouped[primary[row["name"]]["campaign"]].append(row)
	return dict(grouped)


def _load_campaign_lead_page(year, date_from, date_to, campus, channel, scope, campaign_id, status_group, page, page_size):
	"""Load one page from the campaign cohort instead of slicing a full student list in Python."""
	if not all(frappe.db.table_exists(doctype) for doctype in ("CRM Campaign Attribution", "CRM Lead")):
		return None
	attributions = frappe.get_all(
		"CRM Campaign Attribution",
		filters=[
			["attributed_at", ">=", date_from.isoformat()],
			["attributed_at", "<", (date_to + timedelta(days=1)).isoformat()],
		],
		fields=["name", "student", "campaign", "weight", "confidence", "is_first_touch", "attributed_at"],
		limit_page_length=0,
	)
	primary = _primary_attributions(attributions)
	if not primary:
		return {"rows": [], "total": 0}

	campaign_ids = {row["campaign"] for row in primary.values()}
	campaign_filters = {"name": ["in", sorted(campaign_ids)]}
	if campus:
		campaign_filters["campus"] = campus
	visible_campaigns = {
		row["name"]
		for row in frappe.get_list("CRM Campaign", filters=campaign_filters, fields=["name"], limit_page_length=0)
	}
	if not campus:
		visible_campaigns = set(campaign_ids)
	if channel:
		assignments = frappe.get_all(
			"CRM Campaign Channel Assignment",
			filters={"campaign": ["in", sorted(visible_campaigns)], "channel": channel}
			if visible_campaigns
			else {"campaign": ["in", [""]], "channel": channel},
			fields=["campaign"],
			limit_page_length=0,
		)
		visible_campaigns &= {row["campaign"] for row in assignments}
	student_ids = [
		student
		for student, attribution in primary.items()
		if attribution["campaign"] == campaign_id and campaign_id in visible_campaigns
	]
	if not student_ids:
		return {"rows": [], "total": 0}

	year_id = frappe.db.get_value("CRM Admission Year", {"year_name": year}, "name") or year
	filters = {"name": ["in", student_ids], "admission_year": year_id}
	if campus:
		filters["branch"] = campus
	if scope.get("territory"):
		teams = frappe.get_all("CRM Team", filters={"territory": scope["territory"]}, pluck="name")
		filters["owning_team"] = ["in", teams or [""]]
	all_rows = frappe.get_list(
		"CRM Lead",
		filters=filters,
		fields=["name", "lead_code", "student_name", "high_school", "processing_status", "resolution", "owner_staff", "source", "modified"],
		order_by="modified desc, name asc",
		limit_page_length=0,
	)
	if status_group != "all":
		all_rows = [
			row for row in all_rows
			if _lead_status_group(str(row.get("processing_status") or ""), dict(row)) == status_group
		]
	total = len(all_rows)
	rows = all_rows[(page - 1) * page_size : page * page_size]
	for row in rows:
		code = str(row.get("processing_status") or "")
		status = dict(row)
		row.update(
			statusCode=code,
			status=code or "Unknown",
			statusGroup=_lead_status_group(code, status),
		)
	return {"rows": rows, "total": total}


def _lead_counts(rows):
	if rows is None:
		return {
			"leadCount": None,
			"statusBreakdown": None,
			"qualityCount": None,
			"qualityBreakdown": None,
		}
	counts = defaultdict(int)
	for row in rows:
		counts[row["statusGroup"]] += 1
	def breakdown(groups):
		return [{"code": code, "label": label, "count": counts[code],
			"share": round(counts[code] / len(rows) * 100, 1) if rows else 0.0}
			for code, label in groups.items()]
	return {"leadCount": len(rows), "statusBreakdown": breakdown(LEAD_STATUS_GROUPS),
		"qualityCount": sum(counts[code] for code in LEAD_QUALITY_GROUPS),
		"qualityBreakdown": breakdown(LEAD_QUALITY_GROUPS)}


def _build_lead_items(rows):
	if not rows:
		return []
	def labels(doctype, field, ids):
		if not ids:
			return {}
		return {row["name"]: row.get(field) or row["name"] for row in frappe.get_all(
			doctype, filters={"name": ["in", sorted(ids)]}, fields=["name", field], limit_page_length=0)}
	schools = labels("CRM High School", "school_name", {row["high_school"] for row in rows if row.get("high_school")})
	owners = labels("CRM Staff", "full_name", {row["owner_staff"] for row in rows if row.get("owner_staff")})
	sources = labels("CRM Lead Source", "source_name", {row["source"] for row in rows if row.get("source")})
	interactions = frappe.get_list("CRM Interaction",
		filters={"student": ["in", [row["name"] for row in rows]], "direction": "outbound",
			"interaction_datetime": ["is", "set"]},
		fields=["student", "interaction_datetime"], limit_page_length=0)
	contacts = defaultdict(list)
	for interaction in interactions:
		contacts[interaction["student"]].append(str(interaction["interaction_datetime"]))
	return [{"id": row["name"], "leadCode": row.get("lead_code") or row["name"],
		"name": row.get("student_name") or row["name"],
		"school": schools.get(row.get("high_school"), ""), "status": row["status"], "statusCode": row["statusCode"],
		"statusGroup": row["statusGroup"], "owner": owners.get(row.get("owner_staff"), ""),
		"source": sources.get(row.get("source"), ""), "contactAttemptCount": len(contacts[row["name"]]),
		"lastContactAt": max(contacts[row["name"]], default=None),
		"modifiedAt": str(row["modified"]) if row.get("modified") else None} for row in rows]


def require_campaign_intelligence_access() -> dict[str, Any]:
	"""Allow the canonical Director, Marketing, or tightly scoped platform admin."""

	user = getattr(frappe.session, "user", None)
	if not user or user == "Guest":
		raise_api_error(
			"UNAUTHENTICATED", "Bạn cần đăng nhập để truy cập dữ liệu này.", frappe.AuthenticationError, 401
		)
	if frappe.db.get_value("User", user, "enabled") not in (1, True, "1"):
		raise_api_error("UNAUTHENTICATED", "Tài khoản không hoạt động.", frappe.AuthenticationError, 401)
	if user == "Administrator":
		return {"user": user, "profile": "platform_superuser", "roleState": "platform_superuser"}

	roles = frozenset(frappe.get_roles(user))
	role_state = classify_role_set(roles)
	profile = resolve_crm_profile(roles)
	allowed_system_roles = FRAMEWORK_ROLE_NAMES | frozenset(DESK_MANAGEMENT_ROLE_NAMES) | {"System Manager"}
	approved_system_manager = role_state == "system_manager" and not (roles - allowed_system_roles)
	approved_profile = role_state == "canonical_profile" and profile in {"admissions_director", "marketing"}
	forbidden_roles = (
		CANONICAL_PROFILE_ROLES | LEGACY_OVERLAY_ROLES | LEGACY_UNMAPPED_ROLES | ROLE_BACKFILL_SOURCES
	)
	if role_state == "system_manager" and roles & (forbidden_roles - {"System Manager"}):
		approved_system_manager = False
	if not (approved_profile or approved_system_manager):
		raise_api_error(
			"FORBIDDEN",
			"Bạn không có quyền truy cập dữ liệu Campaign Intelligence.",
			frappe.PermissionError,
			403,
		)
	return {"user": user, "profile": profile or "system_manager", "roleState": role_state}


def _resolve_date_range(admission_year: str, from_value: Any, to_value: Any) -> tuple[date, date, list[str]]:
	warnings: list[str] = []
	year_row = frappe.db.get_value(
		"CRM Admission Year", {"year_name": admission_year}, ["start_date", "end_date"], as_dict=True
	)
	default_from = _as_date(year_row.get("start_date")) if year_row else None
	default_to = _as_date(year_row.get("end_date")) if year_row else None
	if not default_from or not default_to:
		default_from, default_to = date(int(admission_year), 1, 1), date(int(admission_year), 12, 31)
		warnings.append("Kỳ tuyển sinh chưa có đủ ngày bắt đầu/kết thúc; đã dùng phạm vi năm dương lịch.")
	date_from = _parse_date(from_value, "from") if from_value not in (None, "") else default_from
	date_to = _parse_date(to_value, "to") if to_value not in (None, "") else default_to
	if date_from > date_to:
		raise_api_error(
			"INVALID_DATE_RANGE",
			"Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.",
			frappe.ValidationError,
			422,
		)
	return date_from, date_to, warnings


def _parse_date(value: Any, field: str) -> date:
	try:
		return date.fromisoformat(str(value).strip())
	except (TypeError, ValueError):
		raise_api_error(
			"INVALID_QUERY", f"Tham số {field} phải có định dạng YYYY-MM-DD.", frappe.ValidationError, 400
		)
		raise AssertionError("raise_api_error always raises")


def _parse_granularity(value: Any) -> str:
	result = str(value or "week").strip().lower()
	if result not in GRANULARITIES:
		raise_api_error("INVALID_QUERY", "Tham số granularity không hợp lệ.", frappe.ValidationError, 400)
	return result


def _resolve_link_filter(field: str, value: Any, doctype: str) -> str | None:
	text = str(value or "all").strip()
	if text.casefold() == "all":
		return None
	if not text or len(text) > 140 or not frappe.db.exists(doctype, text):
		raise_api_error("INVALID_QUERY", f"Tham số {field} không hợp lệ.", frappe.ValidationError, 400)
	return text


def _resolve_scope(value: Any, access: dict[str, Any]) -> dict[str, str | None]:
	text = str(value or "all").strip()
	if text.casefold() == "all":
		return {"id": "all", "territory": None}
	if not text or len(text) > 140:
		raise_api_error("INVALID_QUERY", "Tham số scope không hợp lệ.", frappe.ValidationError, 400)
	territory = frappe.db.get_value("CRM Territory", {"name": text}, "name") or frappe.db.get_value(
		"CRM Territory", {"territory_code": text}, "name"
	)
	if not territory:
		raise_api_error("INVALID_QUERY", "Tham số scope không hợp lệ.", frappe.ValidationError, 400)
	if access["roleState"] not in {"platform_superuser", "system_manager"}:
		staff_territory = frappe.db.get_value(
			"CRM Staff", {"user": access["user"], "is_active": 1}, "territory"
		)
		if staff_territory != territory:
			raise_api_error(
				"FORBIDDEN", "Scope không nằm trong phạm vi được cấp quyền.", frappe.PermissionError, 403
			)
	return {"id": str(territory), "territory": str(territory)}


def _load_facts(
	date_from: date,
	date_to: date,
	campus: str | None,
	channel: str | None,
	scope: dict[str, str | None],
	warnings: list[str],
) -> list[dict[str, Any]]:
	if not frappe.db.table_exists("CRM Campaign Performance Fact"):
		raise_api_error(
			"CAMPAIGN_INTELLIGENCE_DATA_UNAVAILABLE",
			"Nguồn dữ liệu campaign intelligence chưa sẵn sàng.",
			frappe.ValidationError,
			503,
		)
	filters = {"period_start": ["<=", date_to.isoformat()], "period_end": [">=", date_from.isoformat()]}
	rows = [
		dict(row)
		for row in frappe.get_all(
			"CRM Campaign Performance Fact", filters=filters, fields=FACT_FIELDS, limit_page_length=0
		)
	]
	assignment_ids = {row.get("channel_assignment") for row in rows if row.get("channel_assignment")}
	assignments = {
		row["name"]: row
		for row in frappe.get_all(
			"CRM Campaign Channel Assignment",
			filters={"name": ["in", list(assignment_ids)]} if assignment_ids else {"name": ["in", [""]]},
			fields=["name", "campaign", "channel"],
			limit_page_length=0,
		)
	}
	campaign_ids = {row.get("campaign") for row in rows if row.get("campaign")}
	campaign_rows = {
		row["name"]: row
		for row in frappe.get_all(
			"CRM Campaign",
			filters={"name": ["in", list(campaign_ids)]} if campaign_ids else {"name": ["in", [""]]},
			fields=["name", "campus"],
			limit_page_length=0,
		)
	}
	filtered = []
	for row in rows:
		assignment = assignments.get(row.get("channel_assignment"))
		campaign_row = campaign_rows.get(row.get("campaign"))
		if not assignment or not campaign_row:
			warnings.append("Đã bỏ qua fact campaign thiếu quan hệ campaign/channel hợp lệ.")
			continue
		if channel and assignment.get("channel") != channel:
			continue
		if campus and campaign_row.get("campus") != campus:
			continue
		dimensions = _json_object(row.get("dimension_values"))
		if scope.get("territory") and not _matches_scope(dimensions, str(scope["territory"])):
			continue
		row["channel"] = assignment.get("channel")
		filtered.append(row)
	return filtered


def _load_campaigns(campaign_ids: set[str]) -> dict[str, dict[str, Any]]:
	if not campaign_ids:
		return {}
	return {
		row["name"]: dict(row)
		for row in frappe.get_all(
			"CRM Campaign",
			filters={"name": ["in", list(campaign_ids)]},
			fields=["name", "title", "campus"],
			limit_page_length=0,
		)
	}


def _load_attribution(
	campaign_ids: set[str], date_from: date, date_to: date, warnings: list[str]
) -> dict[str, float]:
	if not campaign_ids or not frappe.db.table_exists("CRM Campaign Attribution"):
		return {}
	try:
		rows = frappe.get_all(
			"CRM Campaign Attribution",
			filters={
				"campaign": ["in", list(campaign_ids)],
				"attributed_at": ["between", [date_from, date_to + timedelta(days=1)]],
			},
			fields=["campaign", "confidence"],
			limit_page_length=0,
		)
	except Exception:
		warnings.append("Không thể tải confidence attribution; mức tin cậy sẽ ở ngưỡng thấp.")
		return {}
	grouped: dict[str, list[float]] = defaultdict(list)
	for row in rows:
		grouped[row["campaign"]].append(_number(row.get("confidence")))
	return {campaign: sum(values) / len(values) for campaign, values in grouped.items() if values}


def _build_response(
	admission_year: str,
	date_from: date,
	date_to: date,
	granularity: str,
	scope: dict[str, str | None],
	facts: list[dict[str, Any]],
	campaigns: dict[str, dict[str, Any]],
	attribution: dict[str, float],
	warnings: list[str],
	leads: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
	campaign_rows = _build_campaigns(facts, campaigns, attribution, leads)
	summary = _summary(campaign_rows)
	return {
		"meta": {
			"admissionYear": int(admission_year),
			"from": date_from.isoformat(),
			"to": date_to.isoformat(),
			"granularity": granularity,
			"timezone": "Asia/Ho_Chi_Minh",
			"scope": scope["id"],
			"status": "partial" if warnings else "available",
			"source": "CRM Campaign Performance Fact v1",
			"leadAttributionRule": PRIMARY_ATTRIBUTION_RULE,
			"warnings": list(dict.fromkeys(warnings)),
		},
		"generatedAt": datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
		"summary": summary,
		"trend": _build_trend(facts, granularity),
		"funnel": _build_funnel(facts),
		"campaigns": campaign_rows,
		"recommendation": _recommendation(campaign_rows),
	}


def _build_campaigns(
	facts: list[dict[str, Any]], campaigns: dict[str, dict[str, Any]], attribution: dict[str, float],
	leads: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
	grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for fact in facts:
		grouped[fact["campaign"]].append(fact)
	for campaign_id in leads or {}:
		grouped.setdefault(campaign_id, [])
	rows = []
	for campaign_id, values in grouped.items():
		metrics = _metrics(values)
		spend = metrics["spend"]
		revenue = metrics["confirmedRevenue"]
		enrollment_rate = _percentage(metrics["enrollments"], metrics["applications"])
		confidence = attribution.get(campaign_id, 0.0)
		rows.append(
			{
				"id": campaign_id,
				"name": campaigns.get(campaign_id, {}).get("title") or campaign_id,
				"channel": _single_or_mixed({value.get("channel") for value in values}),
				**metrics,
				**_lead_counts(None if leads is None else (leads or {}).get(campaign_id, [])),
				"roas": _ratio(revenue, spend),
				"cpql": _ratio(spend, metrics["qualifiedLeads"]),
				"enrollmentRate": enrollment_rate,
				"attributionConfidence": _confidence_band(confidence),
				"health": _health(_ratio(revenue, spend), enrollment_rate),
			}
		)
	return sorted(rows, key=lambda row: (-row["spend"], row["name"], row["id"]))


def _metrics(facts: list[dict[str, Any]]) -> dict[str, float | int]:
	return {
		"spend": _money(sum(_number(row.get("spend")) for row in facts)),
		"qualifiedLeads": _whole(sum(_raw_number(row, "qualified_leads", "qualified") for row in facts)),
		"applications": _whole(sum(_number(row.get("applications")) for row in facts)),
		"enrollments": _whole(sum(_number(row.get("enrolled")) for row in facts)),
		"confirmedRevenue": _money(
			sum(_raw_number(row, "confirmed_revenue", "recognized_revenue") for row in facts)
		),
		"pipelineRevenue": _money(sum(_raw_number(row, "pipeline_revenue") for row in facts)),
	}


def _summary(campaigns: list[dict[str, Any]]) -> dict[str, float | int | None]:
	result = {
		field: _money(sum(_number(row[field]) for row in campaigns))
		if "Revenue" in field or field == "spend"
		else _whole(sum(_number(row[field]) for row in campaigns))
		for field in ("spend", "qualifiedLeads", "applications", "enrollments", "confirmedRevenue")
	}
	result["roas"] = _ratio(result["confirmedRevenue"], result["spend"])
	return result


def _build_trend(facts: list[dict[str, Any]], granularity: str) -> list[dict[str, Any]]:
	grouped: dict[date, list[dict[str, Any]]] = defaultdict(list)
	for fact in facts:
		period = _as_date(fact.get("period_start"))
		if period:
			grouped[_bucket(period, granularity)].append(fact)
	return [
		{
			"label": _bucket_label(bucket, granularity),
			"spend": _money(sum(_number(row.get("spend")) for row in values)),
			"confirmedRevenue": _money(
				sum(_raw_number(row, "confirmed_revenue", "recognized_revenue") for row in values)
			),
		}
		for bucket, values in sorted(grouped.items())
	]


def _build_funnel(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
	values = {
		"impressions": _whole(sum(_number(row.get("impressions")) for row in facts)),
		"clicks": _whole(sum(_number(row.get("clicks")) for row in facts)),
		"landingVisits": _whole(sum(_raw_number(row, "landing_visits", "landingVisits") for row in facts)),
		"leads": _whole(sum(_number(row.get("leads")) for row in facts)),
		"qualified": _whole(sum(_raw_number(row, "qualified_leads", "qualified") for row in facts)),
		"applications": _whole(sum(_number(row.get("applications")) for row in facts)),
		"enrollments": _whole(sum(_number(row.get("enrolled")) for row in facts)),
	}
	result = []
	previous = None
	for stage_id, label in FUNNEL_STAGES:
		value = values[stage_id]
		result.append(
			{
				"id": stage_id,
				"label": label,
				"value": value,
				"rate": 100.0 if previous is None else _percentage(value, previous),
			}
		)
		previous = value
	return result


def _recommendation(campaigns: list[dict[str, Any]]) -> dict[str, Any]:
	eligible = [row for row in campaigns if row["spend"] > 0 and row["roas"] is not None]
	if len(eligible) < 2:
		return {
			"title": "Chưa đủ dữ liệu để đề xuất phân bổ lại ngân sách.",
			"impact": None,
			"confidence": "low",
			"evidence": [],
		}
	best, weakest = max(eligible, key=lambda row: row["roas"]), min(eligible, key=lambda row: row["roas"])
	impact = _money(max(best["roas"] - weakest["roas"], 0) * weakest["spend"] * 0.15)
	return {
		"title": f"Ưu tiên ngân sách từ {weakest['name']} sang {best['name']}.",
		"impact": impact,
		"impactHorizon": "14 ngày",
		"confidence": "high"
		if best["attributionConfidence"] == weakest["attributionConfidence"] == "high"
		else "medium",
		"evidence": [f"ROAS {best['name']}: {best['roas']}", f"ROAS {weakest['name']}: {weakest['roas']}"],
	}


def _json_object(value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if not value:
		return {}
	try:
		parsed = json.loads(value)
	except (TypeError, ValueError):
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _raw_number(row: dict[str, Any], *keys: str) -> float:
	values = _json_object(row.get("raw_measures"))
	for key in keys:
		if key in values:
			return _number(values[key])
	return 0.0


def _matches_scope(values: dict[str, Any], territory: str) -> bool:
	return any(str(values.get(key) or "") == territory for key in ("territory", "territory_id", "scope"))


def _as_date(value: Any) -> date | None:
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	try:
		return date.fromisoformat(str(value))
	except (TypeError, ValueError):
		return None


def _bucket(value: date, granularity: str) -> date:
	if granularity == "day":
		return value
	if granularity == "month":
		return value.replace(day=1)
	return value - timedelta(days=value.weekday())


def _bucket_label(value: date, granularity: str) -> str:
	if granularity == "month":
		return f"{value.month:02d}/{value.year}"
	if granularity == "week":
		return f"W{value.isocalendar().week:02d}/{value.year}"
	return value.isoformat()


def _single_or_mixed(values: set[Any]) -> str:
	cleaned = sorted(str(value) for value in values if value)
	return cleaned[0] if len(cleaned) == 1 else "mixed"


def _number(value: Any) -> float:
	try:
		return float(value or 0)
	except (TypeError, ValueError):
		return 0.0


def _whole(value: float) -> int:
	return round(value)


def _money(value: float) -> float:
	return round(value, 2)


def _ratio(numerator: float | int, denominator: float | int) -> float | None:
	return round(float(numerator) / float(denominator), 2) if denominator else None


def _percentage(numerator: float | int, denominator: float | int) -> float | None:
	return round(float(numerator) / float(denominator) * 100, 1) if denominator else None


def _confidence_band(value: float) -> str:
	return "high" if value >= 80 else "medium" if value >= 50 else "low"


def _health(roas: float | None, enrollment_rate: float | None) -> str:
	if roas is None or enrollment_rate is None:
		return "watch"
	return "on_track" if roas >= 1 and enrollment_rate >= 5 else "reallocate"
