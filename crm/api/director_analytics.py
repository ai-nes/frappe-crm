"""Closed, declarative read contract for Admissions Director workspaces.

Phase 1 deliberately publishes definitions only.  It never derives values from
legacy Contact data; absent Student projections are explicitly migration-required.
"""

from __future__ import annotations

from copy import deepcopy
import base64
import hashlib
import hmac
import json
import time

import frappe
from frappe.utils.password import get_encryption_key

DIRECTOR_DEFINITION_VERSION = "director-analytics-v1"
DIRECTOR_SCOPE_LABEL = "Within delegated campus scope"

_ROUTES = {
	"mgr_overview": ("director-overview", "overview"), "mgr_progress_quota": ("director-overview", "quota-progress"),
	"mgr_by_campus": ("director-overview", "campus"), "mgr_by_major": ("director-overview", "program"),
	"mgr_funnel_forecast": ("director-forecast", "funnel"), "mgr_sla_system": ("director-sla", "team"),
	"mgr_sla_by_team": ("director-sla", "team"), "mgr_sla_by_campus": ("director-sla", "campus"),
	"mgr_sla_ranking": ("director-sla", "ranking"), "mgr_all_records": ("director-records", "all"),
	"mgr_teams_staff": ("director-people", "team-performance"), "mgr_team_perf": ("director-people", "team-performance"),
	"mgr_workload": ("director-people", "workload"), "mgr_rebalance": ("director-people", "rebalance"),
	"mgr_marketing_roi": ("marketing-roi", "overview"), "mgr_approvals": ("approvals", "all"),
	"mgr_appr_spend": ("approvals", "spend"), "mgr_appr_master_data": ("approvals", "master-data"),
	"mgr_appr_break_glass": ("approvals", "break-glass"), "mgr_quota_tuition": ("admissions-reference", "quota-tuition"),
	"mgr_business_config": ("business-policy", "sla"), "mgr_cfg_sla": ("business-policy", "sla"),
	"mgr_cfg_distribution": ("business-policy", "distribution"), "mgr_cfg_scoring": ("business-policy", "scoring"),
	"mgr_reports": ("embedded-reports", "catalog"),
}

_FILTERS = {
	"director-overview": ("period", "dateRange", "campus", "program"), "director-forecast": ("period", "dateRange", "campus", "program", "lifecycle"),
	"director-sla": ("period", "dateRange", "campus", "team", "slaBucket"), "director-records": ("period", "dateRange", "campus", "program", "team", "lifecycle", "page", "sort"),
	"director-people": ("period", "dateRange", "campus", "team", "page", "sort"), "marketing-roi": ("period", "dateRange", "campus", "program", "attributionMethod"),
	"approvals": ("period", "dateRange", "campus", "approvalState", "page", "sort"), "admissions-reference": ("campus",),
	"business-policy": ("campus",), "embedded-reports": (),
}

_LABELS = {
	"director-overview": "Tổng quan tuyển sinh", "director-forecast": "Phễu & dự báo", "director-sla": "SLA toàn hệ",
	"director-records": "Hồ sơ (toàn bộ)", "director-people": "Nhóm & nhân sự", "marketing-roi": "Marketing ROI",
	"approvals": "Chờ duyệt", "admissions-reference": "Chỉ tiêu & học phí", "business-policy": "Cấu hình nghiệp vụ", "embedded-reports": "Báo cáo",
}

_FILTER_DESCRIPTORS = {
	"period": {"label": "Thời kỳ", "type": "select", "options": [], "default": None},
	"dateRange": {"label": "Khoảng thời gian", "type": "date-range", "options": [], "default": None},
	"campus": {"label": "Chi nhánh", "type": "select", "options": [], "default": None},
	"program": {"label": "Ngành", "type": "select", "options": [], "default": None},
	"team": {"label": "Nhóm", "type": "select", "options": [], "default": None},
	"lifecycle": {"label": "Giai đoạn hồ sơ", "type": "multi-select", "options": [], "default": []},
	"slaBucket": {"label": "Mức SLA", "type": "select", "options": [], "default": None},
	"attributionMethod": {"label": "Phương pháp phân bổ", "type": "select", "options": [], "default": None},
	"approvalState": {"label": "Trạng thái phê duyệt", "type": "select", "options": [], "default": None},
	"page": {"label": "Trang", "type": "hidden", "options": [], "default": None},
	"sort": {"label": "Sắp xếp", "type": "select", "options": [], "default": None},
}


def _definition(workspace, view):
	metric_id = f"{workspace}.{view}"
	return {
		"id": metric_id, "version": DIRECTOR_DEFINITION_VERSION, "label": _LABELS[workspace],
		"formula": None, "numerator": None, "denominator": None, "unit": "count", "format": "number",
		"sources": ["CRM Lead"], "grain": "state asOf", "asOfRule": "request-time source watermark",
		"businessTimezone": "Asia/Ho_Chi_Minh", "privacyRule": "suppress small aggregates", "scopeLabel": DIRECTOR_SCOPE_LABEL,
	}


DIRECTOR_VIEW_DEFINITIONS = {
	(workspace, view): {
		"definition": _definition(workspace, view), "filterKeys": _FILTERS[workspace], "rowSchema": [],
		"availability": "unavailable", "reason": "The source contract for this view is not released.",
		"metricGrain": {"key": "CRM Lead.name", "classification": "state", "lateArrival": "request-watermark"},
		"dependencyDag": {"sources": ["CRM Lead"], "metrics": [f"{workspace}.{view}"]},
	}
	for workspace, view in sorted(set(_ROUTES.values()))
}

_IMPLEMENTED_VIEWS = frozenset({
	("director-overview", "overview"), ("director-overview", "quota-progress"), ("director-overview", "campus"),
	("director-overview", "program"), ("director-records", "all"), ("director-people", "team-performance"), ("director-people", "workload"),
	("director-forecast", "funnel"), ("director-sla", "team"), ("director-sla", "campus"),
	("director-sla", "ranking"), ("admissions-reference", "quota-tuition"),
})
DIRECTOR_ROUTE_READINESS = {
	menu_id: {"workspace": route[0], "view": route[1], "status": "ready" if route in _IMPLEMENTED_VIEWS else "unavailable"}
	for menu_id, route in _ROUTES.items()
}
_PRIVACY_MINIMUM = 5
_STAGE_ALIASES = {
	"Lead": "New",
	"MQL": "Attempting",
	"Applicant": "Qualified",
	"Enrolled": "Connected",
	"Lost": "Disqualified",
}

# Multi-source readers remain partial until the storage layer supports an
# immutable as-of query.  These fields are immutable opening attribution.
_VIEW_SOURCES = {
	("director-forecast", "funnel"): ("CRM Lead", "CRM Student Lifecycle Event"),
	("director-sla", "team"): ("CRM Student SLA Attempt", "CRM Student SLA Event"),
	("director-sla", "campus"): ("CRM Student SLA Attempt", "CRM Student SLA Event"),
	("director-sla", "ranking"): ("CRM Student SLA Attempt", "CRM Student SLA Event"),
	("admissions-reference", "quota-tuition"): ("CRM Admission Year", "CRM Academic Year Config", "CRM Academic Year Line", "CRM Lead"),
}
for _route, _sources in _VIEW_SOURCES.items():
	DIRECTOR_VIEW_DEFINITIONS[_route]["definition"].update({"sources": list(_sources), "grain": "event" if _route[0] in {"director-forecast", "director-sla"} else "configured reference"})


def is_director_view(workspace, view):
	return (workspace, view) in DIRECTOR_VIEW_DEFINITIONS


def filter_keys(workspace, view):
	definition = DIRECTOR_VIEW_DEFINITIONS.get((workspace, view))
	return definition["filterKeys"] if definition else ()


def route_is_ready(workspace, view):
	return (workspace, view) in _IMPLEMENTED_VIEWS


def snapshot_context(policy, workspace, view, filters):
	"""Preflight every source before issuing a usable analytics snapshot."""
	sources = _VIEW_SOURCES.get((workspace, view), ("CRM Lead",))
	if not route_is_ready(workspace, view) or not all(_source_available(source) for source in sources):
		return None
	watermarks = {source: _watermark(source) for source in sources}
	if not all(watermarks.values()):
		return None
	return {"definitionVersion": DIRECTOR_DEFINITION_VERSION, "timezone": "Asia/Ho_Chi_Minh", "asOf": str(max(watermarks.values())), "watermarks": {source: str(value) for source, value in watermarks.items()}}


def _encode(value): return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
def _decode(value): return base64.urlsafe_b64decode(f"{value}{'=' * (-len(value) % 4)}")
def _token_secret(): return f"crm-director-row:{get_encryption_key()}".encode()


def mint_row_detail_token(policy, snapshot, student):
	payload = {"actor": policy.actor, "scope": policy.scope_version, "snapshot": snapshot, "student": student, "expiresAt": int(time.time()) + 300}
	body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
	return f"{_encode(body)}.{_encode(hmac.new(_token_secret(), body, hashlib.sha256).digest())}"


def validate_row_detail_token(token, policy, snapshot):
	try:
		body_token, signature_token = token.split(".", 1); body, signature = _decode(body_token), _decode(signature_token)
		payload = json.loads(body)
		if not hmac.compare_digest(signature, hmac.new(_token_secret(), body, hashlib.sha256).digest()) or payload["expiresAt"] < time.time() or payload["actor"] != policy.actor or payload["scope"] != policy.scope_version or payload["snapshot"] != snapshot:
			raise ValueError
		return payload["student"]
	except (ValueError, KeyError, TypeError, UnicodeDecodeError):
		frappe.throw("Director row token is invalid or expired.", frappe.PermissionError)


def _response(kind, snapshot, workspace, view, filters):
	definition = deepcopy(DIRECTOR_VIEW_DEFINITIONS[(workspace, view)])
	snapshot_context = {"definitionVersion": DIRECTOR_DEFINITION_VERSION, "timezone": definition["definition"]["businessTimezone"], "asOf": None, "watermarks": {source: "unreleased" for source in definition["definition"]["sources"]}}
	availability = {"status": definition["availability"], "reason": definition["reason"], "coverage": None, "asOf": snapshot_context["asOf"], "watermarks": snapshot_context["watermarks"]}
	response = {"contractStatus": definition["availability"], "snapshot": snapshot, "snapshotContext": snapshot_context, "definitionVersion": DIRECTOR_DEFINITION_VERSION, "definition": definition["definition"], "availability": availability, "filters": filters, "scopeLabel": DIRECTOR_SCOPE_LABEL}
	if kind == "summary": response.update({"title": definition["definition"]["label"], "filterSchema": [{"key": key, **_FILTER_DESCRIPTORS[key]} for key in definition["filterKeys"]], "kpis": [], "actions": [], "drillDown": []})
	elif kind == "series": response.update({"series": [], "dateCoverage": None})
	elif kind == "rows": response.update({"rows": [], "cursor": None, "total": None, "rowSchema": definition["rowSchema"]})
	elif kind == "export": response.update({"download": None, "oneUse": True})
	return response


def _source_available(doctype):
	return bool(frappe.db.table_exists(doctype))


def _student_filters(policy, filters):
	result = {"branch": ["in", list(policy.campuses)]}
	for source, target in (("program", "major"), ("team", "owning_team"), ("lifecycle", "student_stage")):
		if filters.get(source):
			if source == "lifecycle":
				values = filters[source] if isinstance(filters[source], list) else [filters[source]]
				result[target] = ["in", [_STAGE_ALIASES.get(value, value) for value in values]]
			else:
				result[target] = filters[source]
	return result


def _watermark(doctype):
	return frappe.db.get_value(doctype, {}, "max(modified)") if _source_available(doctype) else None


def _ready_response(kind, snapshot, workspace, view, filters, *, kpis=None, series=None, rows=None, row_schema=None, total=None, reason=None):
	response = _response(kind, snapshot, workspace, view, filters)
	definition = response["definition"]
	sources = _VIEW_SOURCES.get((workspace, view), ("CRM Lead",))
	watermarks = {source: _watermark(source) for source in sources}
	watermark = max((value for value in watermarks.values() if value), default=None)
	# The current Frappe reader has no immutable/as-of predicate.  Keep live
	# values usable but never represent them as the snapshot's exact boundary.
	response.update({"contractStatus": "partial", "availability": {"status": "partial", "reason": reason or "Dữ liệu đang được đọc trực tiếp từ CRM; số liệu có thể thay đổi khi có cập nhật mới.", "coverage": list(sources), "asOf": watermark, "watermarks": watermarks}, "snapshotContext": {"definitionVersion": DIRECTOR_DEFINITION_VERSION, "timezone": definition["businessTimezone"], "asOf": watermark, "watermarks": watermarks}})
	if kpis is not None: response["kpis"] = kpis
	if series is not None: response["series"] = series
	if rows is not None: response.update({"rows": rows, "rowSchema": row_schema or [], "total": total})
	return response


def _student_kpis(policy, filters):
	student_filters = _student_filters(policy, filters)
	total = frappe.db.count("CRM Student", filters=student_filters)
	stages = frappe.db.get_all("CRM Student", filters=student_filters, fields=["student_stage", "count(name) as value"], group_by="student_stage")
	child_suppressed = any(row.value < _PRIVACY_MINIMUM for row in stages)
	visible_total = total if total >= _PRIVACY_MINIMUM and not child_suppressed else None
	return [
		{"metricId": "students.total", "definitionId": "students.total", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Students", "value": visible_total, "unit": "count", "nullReason": None if visible_total is not None else "privacy_suppressed"},
		{"metricId": "students.enrolled", "definitionId": "students.enrolled", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Enrolled", "value": next((row.value for row in stages if row.student_stage == "Connected"), 0) if visible_total is not None else None, "unit": "count", "nullReason": None if visible_total is not None else "privacy_suppressed"},
	], stages


def _student_series(policy, filters, dimension="student_stage"):
	rows = frappe.db.get_all("CRM Student", filters=_student_filters(policy, filters), fields=[f"{dimension} as label", "count(name) as value"], group_by=dimension, order_by=f"{dimension} asc")
	points = [{"label": row.label or "Unspecified", "value": row.value if row.value >= _PRIVACY_MINIMUM else None, "suppressed": row.value < _PRIVACY_MINIMUM} for row in rows]
	return [{"metricId": "students.count", "definitionId": "students.count", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "points": points, "unit": "count"}]


def _unavailable_for(kind, snapshot, workspace, view, filters, reason):
	response = _response(kind, snapshot, workspace, view, filters)
	response.update({"contractStatus": "unavailable", "availability": {"status": "unavailable", "reason": reason, "coverage": None, "asOf": None, "watermarks": {source: _watermark(source) for source in _VIEW_SOURCES.get((workspace, view), ())}}})
	return response


def _sla_attempts(policy, filters):
	criteria = {"campus": ["in", list(policy.campuses)], "closed_at": ["is", "set"]}
	if filters.get("campus"):
		criteria["campus"] = filters["campus"]
	if filters.get("team"):
		criteria["owning_team"] = filters["team"]
	# owning_team/campus are copied to the attempt at opening and are immutable.
	return frappe.db.get_all("CRM Student SLA Attempt", filters=criteria, fields=["name", "owning_team", "owner_staff", "campus", "closed_at"])


def _sla_projection(policy, filters, dimension):
	attempts = _sla_attempts(policy, filters)
	if not attempts:
		return []
	breached = {row.sla_attempt for row in frappe.db.get_all("CRM Student SLA Event", filters={"sla_attempt": ["in", [row.name for row in attempts]], "event_type": "breached"}, fields=["sla_attempt"])}
	groups = {}
	for attempt in attempts:
		key = attempt.get(dimension) or "Unspecified"
		entry = groups.setdefault(key, {"label": key, "closedAttempts": 0, "breachedAttempts": 0})
		entry["closedAttempts"] += 1
		entry["breachedAttempts"] += int(attempt.name in breached)
	result = []
	for entry in groups.values():
		if entry["closedAttempts"] < _PRIVACY_MINIMUM:
			entry.update({"closedAttempts": None, "breachedAttempts": None, "breachRate": None, "suppressed": True})
		else:
			entry.update({"breachRate": (entry["breachedAttempts"] / entry["closedAttempts"]) * 100, "suppressed": False})
		result.append(entry)
	return sorted(result, key=lambda row: (row["label"] or ""))


def _forecast_series(policy, filters):
	# Current Frappe projections do not retain an immutable eligible-cohort
	# denominator.  Return lifecycle evidence, but withhold every forecast.
	rows = frappe.db.get_all("CRM Student", filters=_student_filters(policy, filters), fields=["student_stage as label", "count(name) as value"], group_by="student_stage")
	return [{"metricId": "funnel.current_state", "definitionId": "funnel.current_state", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Phân bổ hồ sơ hiện tại", "grain": "state_as_of", "points": [{"label": row.label or "Unspecified", "value": row.value if row.value >= _PRIVACY_MINIMUM else None, "suppressed": row.value < _PRIVACY_MINIMUM} for row in rows], "forecast": {"status": "insufficient_forecast_data", "horizonDays": 90, "methodVersion": "cohort-backtest-v1", "reason": "Lifecycle events do not yet prove six completed eligible cohorts and three rolling backtests."}}]


def _quota_rows(policy, filters):
	years = frappe.db.get_all("CRM Admission Year", filters={"is_active": 1}, fields=["name", "modified"])
	if len(years) != 1:
		return None, "Exactly one active CRM Admission Year is required."
	configs = frappe.db.get_all("CRM Academic Year Config", filters={"admission_year": years[0].name}, fields=["name", "modified", "owner"])
	if len(configs) != 1:
		return None, "Exactly one Academic Year Config for the active admission year is required."
	lines = frappe.db.get_all("CRM Academic Year Line", filters={"parent": configs[0].name, "parenttype": "CRM Academic Year Config", "campus": ["in", list(policy.campuses)]}, fields=["name", "line_kind", "campus", "major", "amount", "quota", "note"])
	keys, result = set(), []
	for line in lines:
		# A broad/global line is intentionally not inferred for a campus/major.
		if not line.campus or not line.major:
			continue
		key = (line.line_kind, line.campus, line.major)
		if key in keys:
			return None, "Duplicate quota or tuition lines make the active configuration ambiguous."
		keys.add(key)
		result.append({**dict(line), "admissionYear": years[0].name, "configuration": configs[0].name, "configurationVersion": configs[0].modified})
	return result, None


def get_summary(policy, workspace, view, filters, snapshot):
	if not route_is_ready(workspace, view) or not all(_source_available(source) for source in _VIEW_SOURCES.get((workspace, view), ("CRM Lead",))):
		return _response("summary", snapshot, workspace, view, filters)
	if (workspace, view) == ("director-forecast", "funnel"):
		return _ready_response("summary", snapshot, workspace, view, filters, kpis=[{"metricId": "forecast.status", "definitionId": "forecast.status", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Dự báo tuyển sinh", "value": None, "unit": "count", "nullReason": "insufficient_forecast_data"}], reason="Chưa đủ dữ liệu cohort đã hoàn tất để hiển thị dự báo đáng tin cậy.")
	if workspace == "director-sla":
		projection = _sla_projection(policy, filters, "owning_team" if view != "campus" else "campus")
		closed = sum(row["closedAttempts"] or 0 for row in projection)
		breached = sum(row["breachedAttempts"] or 0 for row in projection)
		return _ready_response("summary", snapshot, workspace, view, filters, kpis=[{"metricId": "sla.closed_attempts", "definitionId": "sla.closed_attempts", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Lượt SLA đã đóng", "value": closed if closed >= _PRIVACY_MINIMUM else None, "unit": "count", "nullReason": None if closed >= _PRIVACY_MINIMUM else "privacy_suppressed"}, {"metricId": "sla.breached_attempts", "definitionId": "sla.breached_attempts", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Lượt vi phạm SLA", "value": breached if closed >= _PRIVACY_MINIMUM else None, "unit": "count", "nullReason": None if closed >= _PRIVACY_MINIMUM else "privacy_suppressed"}])
	if (workspace, view) == ("admissions-reference", "quota-tuition"):
		rows, reason = _quota_rows(policy, filters)
		if reason:
			return _unavailable_for("summary", snapshot, workspace, view, filters, reason)
		return _ready_response("summary", snapshot, workspace, view, filters, kpis=[{"metricId": "reference.lines", "definitionId": "reference.lines", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Dòng chỉ tiêu và học phí", "value": len(rows), "unit": "count", "nullReason": None}])
	if workspace == "director-overview":
		kpis, _ = _student_kpis(policy, filters)
		return _ready_response("summary", snapshot, workspace, view, filters, kpis=kpis)
	if workspace == "director-records":
		return _ready_response("summary", snapshot, workspace, view, filters, kpis=[])
	if workspace == "director-people" and view in {"team-performance", "workload"}:
		return _ready_response("summary", snapshot, workspace, view, filters, kpis=[])
	return _response("summary", snapshot, workspace, view, filters)


def get_series(policy, workspace, view, filters, snapshot):
	if not route_is_ready(workspace, view) or not all(_source_available(source) for source in _VIEW_SOURCES.get((workspace, view), ("CRM Lead",))):
		return _response("series", snapshot, workspace, view, filters)
	if (workspace, view) == ("director-forecast", "funnel"):
		return _ready_response("series", snapshot, workspace, view, filters, series=_forecast_series(policy, filters), reason="Chưa đủ dữ liệu cohort đã hoàn tất để hiển thị dự báo đáng tin cậy.")
	if workspace == "director-sla":
		dimension = "owning_team" if view != "campus" else "campus"
		projection = _sla_projection(policy, filters, dimension)
		return _ready_response("series", snapshot, workspace, view, filters, series=[{"metricId": "sla.closed_attempts", "definitionId": "sla.closed_attempts", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Lượt SLA đã đóng", "unit": "count", "points": [{"label": row["label"], "value": row["closedAttempts"], "suppressed": row["suppressed"]} for row in projection]}, {"metricId": "sla.breach_rate", "definitionId": "sla.breach_rate", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Tỷ lệ vi phạm SLA", "unit": "percent", "points": [{"label": row["label"], "value": row["breachRate"], "suppressed": row["suppressed"]} for row in projection]}])
	if (workspace, view) == ("admissions-reference", "quota-tuition"):
		rows, reason = _quota_rows(policy, filters)
		if reason:
			return _unavailable_for("series", snapshot, workspace, view, filters, reason)
		return _ready_response("series", snapshot, workspace, view, filters, series=[{"metricId": "reference.quota", "definitionId": "reference.quota", "definitionVersion": DIRECTOR_DEFINITION_VERSION, "label": "Chỉ tiêu theo chi nhánh và ngành", "unit": "count", "points": [{"label": f"{row['campus']} · {row['major']}", "value": row.get("quota"), "suppressed": False} for row in rows if row.get("line_kind") == "quota"]}])
	if workspace == "director-overview":
		dimension = "branch" if view == "campus" else "major" if view == "program" else "student_stage"
		return _ready_response("series", snapshot, workspace, view, filters, series=_student_series(policy, filters, dimension))
	if workspace == "director-people" and view in {"team-performance", "workload"}:
		return _ready_response("series", snapshot, workspace, view, filters, series=_student_series(policy, filters, "owning_team"))
	return _response("series", snapshot, workspace, view, filters)


_STUDENT_ROW_FIELDS = ["name", "full_name as student_name", "branch", "major", "student_stage", "owner_staff", "owning_team", "modified"]


def get_rows(policy, workspace, view, filters, snapshot, cursor=None):
	if route_is_ready(workspace, view) and workspace != "director-records":
		return _ready_response("rows", snapshot, workspace, view, filters, rows=[], row_schema=[])
	if workspace != "director-records" or not _source_available("CRM Student"):
		return _response("rows", snapshot, workspace, view, filters)
	page_length = 50
	rows = frappe.db.get_all("CRM Student", filters=_student_filters(policy, filters), fields=_STUDENT_ROW_FIELDS, order_by="modified desc, name desc", limit_page_length=page_length)
	# A logical destination is intentionally emitted instead of raw Contact links.
	projected = [{key: row.get(key) for key in _STUDENT_ROW_FIELDS if key != "name"} | {"drillDown": {"kind": "student", "resolver": "crm.api.role_workspaces.resolve_workspace_row_detail", "token": mint_row_detail_token(policy, snapshot, row.name)}} for row in rows]
	return _ready_response("rows", snapshot, workspace, view, filters, rows=projected, row_schema=[{"field": field, "redaction": "standard"} for field in _STUDENT_ROW_FIELDS if field != "name"], total=None)


def get_export(policy, workspace, view, filters, snapshot, export_id=None):
	if workspace != "director-records":
		return _response("export", snapshot, workspace, view, filters)
	response = get_rows(policy, workspace, view, filters, snapshot)
	if response["contractStatus"] != "ready":
		return _response("export", snapshot, workspace, view, filters)
	# Streaming/download-token transport is deliberately deferred until a one-use
	# downloader exists; this confirms the exact server-defined row projection.
	response.update({"download": None, "oneUse": True, "exportStatus": "unavailable", "exportReason": "The one-use download transport is not released."})
	return response


def get_badges(policy, mint_snapshot):
	# No counts are exposed until recipient-filtered notification readers exist.
	return {"mgr_approvals": {"contractStatus": "migration_required", "count": None, "snapshot": mint_snapshot(policy, "approvals", "all", {})}}
