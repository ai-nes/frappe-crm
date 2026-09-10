"""Permission-scoped aggregate Student 360 quality and outcome metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean

import frappe
from frappe import _


def _require_authenticated():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)


def _students(filters: dict) -> list:
	allowed = {"branch", "current_grade", "study_stage", "source"}
	query = {
		key: value for key, value in (filters or {}).items() if key in allowed and value not in (None, "")
	}
	fields = [
		"name",
		"full_name",
		"phone",
		"high_school",
		"current_grade",
		"study_stage",
		"source",
		"student_stage",
		"interest_level",
		"fit_level",
		"assessment_status",
		"assessment_revision",
	]
	rows, offset, page_size = [], 0, 1000
	while True:
		page = frappe.get_list(
			"CRM Student",
			filters=query,
			fields=fields,
			limit_start=offset,
			limit_page_length=page_size,
			order_by="name asc",
		)
		rows.extend(page)
		if len(page) < page_size:
			return rows
		offset += page_size


def _pct(numerator: int, denominator: int) -> float:
	return round((100.0 * numerator / denominator), 1) if denominator else 0.0


def _is_enrolled(row) -> bool:
	return str(row.get("student_stage") or "").casefold() == "connected"


def _interactions(student_ids: list[str]) -> list:
	if not student_ids or not frappe.db.table_exists("CRM Interaction"):
		return []
	rows, offset, page_size = [], 0, 1000
	while True:
		page = frappe.get_list(
			"CRM Interaction",
			filters={"student": ["in", student_ids]},
			fields=["name", "student", "summary", "direction", "interaction_datetime", "creation"],
			limit_start=offset,
			limit_page_length=page_size,
			order_by="interaction_datetime asc, creation asc, name asc",
		)
		rows.extend(page)
		if len(page) < page_size:
			return rows
		offset += page_size


def _first_response_minutes(rows: list) -> list[float]:
	by_student = defaultdict(list)
	for row in rows:
		if row.get("student"):
			by_student[row.student].append(row)
	values = []
	for student_rows in by_student.values():
		inbound = next(
			(row for row in student_rows if str(row.get("direction") or "").casefold() == "inbound"), None
		)
		if not inbound:
			continue
		start = inbound.get("interaction_datetime") or inbound.get("creation")
		if not start:
			continue
		for response in student_rows:
			if str(response.get("direction") or "").casefold() != "outbound":
				continue
			end = response.get("interaction_datetime") or response.get("creation")
			if not end:
				continue
			try:
				seconds = (
					(end - start).total_seconds()
					if isinstance(end, datetime) and isinstance(start, datetime)
					else (
						datetime.fromisoformat(str(end)).replace(tzinfo=None)
						- datetime.fromisoformat(str(start)).replace(tzinfo=None)
					).total_seconds()
				)
			except (TypeError, ValueError):
				continue
			if seconds >= 0:
				values.append(round(seconds / 60.0, 1))
			break
	return values


def _assessment_metrics(student_ids: list[str]) -> dict:
	if not student_ids or not frappe.db.table_exists("CRM Student Assessment"):
		return {"confirmed_count": 0, "system_correction_rate": 0.0, "high_interest_enrollment_rate": 0.0}
	rows, offset, page_size = [], 0, 1000
	while True:
		page = frappe.get_list(
			"CRM Student Assessment",
			filters={"student": ["in", student_ids], "status": "confirmed"},
			fields=["student", "interest", "override_reason", "assessment_source", "assessment_revision"],
			limit_start=offset,
			limit_page_length=page_size,
		)
		rows.extend(page)
		if len(page) < page_size:
			break
		offset += page_size
	confirmed = len(rows)
	system_rows = [row for row in rows if row.get("assessment_source") == "system"]
	corrected = sum(bool(str(row.get("override_reason") or "").strip()) for row in system_rows)
	return {
		"confirmed_count": confirmed,
		"system_confirmed_count": len(system_rows),
		"system_correction_rate": _pct(corrected, len(system_rows)),
	}


def _campaign_costs(student_ids: list[str]) -> dict:
	"""Return spend/enrollment by campaign without exposing Student identifiers."""
	if (
		not student_ids
		or not frappe.db.table_exists("CRM Marketing Engagement")
		or not frappe.db.table_exists("CRM Campaign Spend")
	):
		return {}
	from crm.fcrm.attribution import get_last_touch_campaign_by_student

	last_touch = get_last_touch_campaign_by_student(student_ids)
	enrolled = Counter()
	for row in frappe.get_list(
		"CRM Student",
		filters={"name": ["in", student_ids]},
		fields=["name", "student_stage"],
		limit_page_length=0,
	):
		if _is_enrolled(row) and last_touch.get(row.name):
			enrolled[last_touch[row.name]] += 1
	spend_rows = frappe.get_list(
		"CRM Campaign Spend",
		fields=["crm_campaign", "amount"],
		filters={"crm_campaign": ["in", list(enrolled)]},
		limit_page_length=0,
	)
	spend = Counter()
	for row in spend_rows:
		if row.get("crm_campaign"):
			spend[row.crm_campaign] += float(row.get("amount") or 0)
	return {
		campaign: {
			"spend": round(spend[campaign], 2),
			"enrolled": enrolled[campaign],
			"cost_per_enrolled": round(spend[campaign] / enrolled[campaign], 2)
			if enrolled[campaign]
			else None,
		}
		for campaign in sorted(set(spend) | set(enrolled))
	}


@frappe.whitelist()
def get_student_360_metrics(filters=None) -> dict:
	"""Return aggregate Student 360 metrics over the caller's visible Students."""
	_require_authenticated()
	if isinstance(filters, str):
		filters = frappe.parse_json(filters) or {}
	if not isinstance(filters, dict):
		frappe.throw(_("filters must be an object."), frappe.ValidationError)
	rows = _students(filters)
	student_ids = [row.name for row in rows]
	interactions = _interactions(student_ids)
	response_minutes = _first_response_minutes(interactions)
	interaction_by_student = Counter(row.student for row in interactions if row.get("summary"))
	profiled = sum(
		bool(
			row.get("full_name")
			and row.get("phone")
			and row.get("high_school")
			and (row.get("current_grade") or row.get("study_stage"))
			and row.get("source")
			and interaction_by_student[row.name]
		)
		for row in rows
	)
	source_counts = Counter(row.get("source") or "Unknown" for row in rows)
	stage_counts = Counter(row.get("study_stage") or row.get("current_grade") or "Unknown" for row in rows)
	grade_10_11 = sum(str(row.get("current_grade") or "") in {"10", "11"} for row in rows)
	high_interest = [
		row
		for row in rows
		if row.get("assessment_status") == "confirmed" and row.get("interest_level") == "High"
	]
	return {
		"generated_at": str(frappe.utils.now_datetime()),
		"cohort": {"visible_students": len(rows), "filters": filters},
		"data_coverage": {
			"minimum_profile_count": profiled,
			"minimum_profile_rate": _pct(profiled, len(rows)),
			"source_rate": _pct(sum(bool(row.get("source")) for row in rows), len(rows)),
			"grade_rate": _pct(
				sum(bool(row.get("current_grade") or row.get("study_stage")) for row in rows), len(rows)
			),
			"grade_10_11_rate": _pct(grade_10_11, len(rows)),
		},
		"classification": {
			**_assessment_metrics(student_ids),
			"high_interest_count": len(high_interest),
			"high_interest_enrollment_rate": _pct(
				sum(_is_enrolled(row) for row in high_interest), len(high_interest)
			),
		},
		"care": {
			"first_response_minutes_avg": round(mean(response_minutes), 1) if response_minutes else None,
			"interactions_with_content": sum(bool(row.get("summary")) for row in interactions),
		},
		"by_source": dict(sorted(source_counts.items())),
		"by_study_stage": dict(sorted(stage_counts.items())),
		"cost_per_enrolled_by_campaign": _campaign_costs(student_ids),
	}
