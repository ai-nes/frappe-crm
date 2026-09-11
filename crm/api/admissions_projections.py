"""Permissioned server-side read contracts for the admissions dashboards."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

from crm.api.admissions_dashboard_auth import check_dashboard_access
from crm.fcrm.admissions_contracts import normalize_filters
from crm.fcrm.admissions_projections import build_projection


def _filters(value: Any = None, **legacy_values) -> dict[str, Any]:
	if isinstance(value, str):
		value = json.loads(value or "{}")
	if value is None:
		value = {}
	if not isinstance(value, dict):
		frappe.throw(_("Projection filters must be an object."), frappe.ValidationError)
	return normalize_filters(
		{**value, **{key: val for key, val in legacy_values.items() if val not in (None, "")}}
	)


def _has_table(doctype: str) -> bool:
	return bool(frappe.db.exists("DocType", doctype))


def _student_scope(staff_names):
	if staff_names is None:
		return None
	if not _has_table("CRM Student"):
		return []
	return frappe.get_list(
		"CRM Student",
		filters={"owner_staff": ["in", staff_names or ["__none__"]]},
		fields=["name"],
		limit_page_length=0,
		pluck="name",
	)


def _meta_fields(doctype: str) -> set[str]:
	return {field.fieldname for field in frappe.get_meta(doctype).fields}


def _safe_filters(doctype: str, filters: dict[str, Any], student_names=None) -> dict[str, Any]:
	fields = _meta_fields(doctype)
	result = {}
	for fieldname in (
		"admission_year",
		"campus",
		"major",
		"campaign",
		"channel",
		"owner",
		"team",
		"planning_scope",
		"metric_key",
		"source_system",
		"status",
	):
		value = filters.get(fieldname)
		if value is None:
			continue
		if fieldname == "channel" and fieldname not in fields and "channel_assignment" in fields:
			result["channel_assignment"] = value
		elif fieldname in fields:
			result[fieldname] = value
	if "period_start" in fields and filters.get("from_date"):
		result["period_start"] = [">=", filters["from_date"]]
	if "period_end" in fields and filters.get("to_date"):
		result["period_end"] = ["<=", filters["to_date"]]
	if student_names is not None and "student" in fields:
		result["student"] = ["in", student_names or ["__none__"]]
	return result


def _rows(doctype: str, fields: list[str], filters: dict[str, Any], student_names=None, limit=50000):
	if not _has_table(doctype):
		return []
	available = _meta_fields(doctype)
	selected = [field for field in fields if field in available]
	return frappe.get_list(
		doctype,
		filters=_safe_filters(doctype, filters, student_names),
		fields=selected,
		limit_page_length=limit,
		order_by="modified desc",
	)


def _staff_scope(dashboard: str):
	return check_dashboard_access(dashboard)


def _overview_data(filters, student_names):
	applications = _rows(
		"CRM Admission Application",
		["name", "student", "admission_year", "campus", "major", "status", "submitted_at", "enrolled_at"],
		filters,
		student_names,
	)
	by_status: dict[str, int] = {}
	for row in applications:
		status = row.get("status") or "Unknown"
		by_status[status] = by_status.get(status, 0) + 1
	return {
		"application_count": len(applications),
		"student_count": len({row.get("student") for row in applications if row.get("student")}),
		"by_status": dict(sorted(by_status.items())),
		"enrolled_count": by_status.get("Enrolled", 0),
		"target_count": _approved_target_count(filters),
	}


def _approved_target_count(filters):
	if not _has_table("CRM Target"):
		return None
	rows = _rows(
		"CRM Target",
		["target_value", "status", "planning_scope", "effective_from", "effective_until"],
		filters,
	)
	return sum(float(row.get("target_value") or 0) for row in rows if row.get("status") == "Approved")


def _performance_data(filters, student_names, field_marketing=False):
	canonical = _has_table("CRM Campaign Performance Fact") and not frappe.conf.get(
		"admissions_legacy_performance_read"
	)
	doctype = "CRM Campaign Performance Fact" if canonical else "CRM Campaign Performance Period"
	fields = [
		"campaign",
		"period_start",
		"period_end",
		"spend",
		"impressions",
		"clicks",
		"leads",
		"applications",
		"enrolled",
		"recognized_revenue",
	]
	if canonical:
		fields = [
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
			"recorded_at",
			"revision",
			"source_system",
		]
	rows = _rows(doctype, fields, filters, student_names=None)
	return {
		"channel_boundary": "Field" if field_marketing else "Digital",
		"source_fact": doctype,
		"source_mode": "canonical" if canonical else "legacy_compatibility",
		"periods": rows,
		"total_spend": sum(float(row.get("spend") or 0) for row in rows),
		"total_leads": sum(int(row.get("leads") or 0) for row in rows),
		"total_applications": sum(int(row.get("applications") or 0) for row in rows),
		"total_enrolled": sum(int(row.get("enrolled") or 0) for row in rows),
		"recognized_revenue": sum(float(row.get("recognized_revenue") or 0) for row in rows),
	}


def _student_360_data(filters, student_names):
	applications = _rows(
		"CRM Admission Application",
		["student", "admission_year", "major", "campus", "status", "document_total", "document_completed"],
		filters,
		student_names,
	)
	events = _rows(
		"CRM Student Engagement Event",
		["student", "event_type", "occurred_at", "campaign", "consent_state"],
		filters,
		student_names,
	)
	return {
		"applications": applications,
		"engagement_events": events,
		"student_count": len({row.get("student") for row in applications}),
	}


@frappe.whitelist()
def get_admissions_overview(filters=None, **kwargs):
	filters = _filters(filters, **kwargs)
	staff_names = _staff_scope("admissions_director")
	return build_projection(
		"AdmissionsOverview",
		filters,
		_overview_data(filters, _student_scope(staff_names)),
		source_mode="canonical_application",
		subject_grain="Application",
	)
@frappe.whitelist()
def get_digital_marketing_overview(filters=None, **kwargs):
	filters = _filters(filters, **kwargs)
	staff_names = _staff_scope("digital_marketing")
	data = _performance_data(filters, _student_scope(staff_names))
	return build_projection("DigitalMarketingOverview", filters, data, source_mode=data["source_mode"])


@frappe.whitelist()
def get_field_marketing_overview(filters=None, **kwargs):
	filters = _filters(filters, **kwargs)
	staff_names = _staff_scope("offline_marketing")
	data = _performance_data(filters, _student_scope(staff_names), field_marketing=True)
	return build_projection("FieldMarketingOverview", filters, data, source_mode=data["source_mode"])


@frappe.whitelist()
def get_student_360(filters=None, **kwargs):
	filters = _filters(filters, **kwargs)
	staff_names = _staff_scope("sale")
	return build_projection(
		"Student360",
		filters,
		_student_360_data(filters, _student_scope(staff_names)),
		source_mode="canonical_application",
		subject_grain="Application",
	)
