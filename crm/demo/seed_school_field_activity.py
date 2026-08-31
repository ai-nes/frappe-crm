"""Deterministic local fixtures for the Director school field activity API.

The fixture uses the operational and planning fields on ``CRM School Activity``.
It also creates append-only Student engagement projections for a bounded subset so
the API can demonstrate canonical attribution without treating attendance or a
raw form count as an enrolled Student.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
from typing import Any

import frappe
from frappe.utils import now_datetime

NAMESPACE = "crm-demo-showcase:director-school-field-activity"


def seed(context: dict[str, Any]) -> dict[str, Any]:
	"""Refresh showcase-owned field activities and their safe attribution facts."""
	if not frappe.db.table_exists("CRM School Activity"):
		return {"status": "skipped", "reason": "school_activity_doctype_unavailable"}

	year = str(context["admission_year"])
	activities = [
		dict(row)
		for row in frappe.get_all(
			"CRM School Activity",
			filters={"owner_staff": ["is", "set"]},
			fields=[
				"name", "high_school", "admission_year", "activity_type", "activity_date",
				"scheduled_datetime", "owner_staff", "status", "attendance",
				"prospect_count", "contact_count", "application_count",
			],
			order_by="high_school asc, activity_date asc, name asc",
			limit_page_length=0,
		)
		or []
	]
	if not activities:
		return {"status": "skipped", "reason": "showcase_activities_unavailable"}

	school_names = sorted({row["high_school"] for row in activities if row.get("high_school")})
	students_by_school = _students_by_school(year, school_names)
	activity_index_by_school: dict[str, int] = defaultdict(int)
	metrics = {
		"status": "available",
		"activities_updated": 0,
		"completed_activities": 0,
		"upcoming_plans": 0,
		"engagement_events_created": 0,
		"engagement_events_replayed": 0,
		"students_attributed": 0,
		"errors": [],
	}
	now = now_datetime()

	for row in activities:
		school = row.get("high_school")
		if not school:
			continue
		index = activity_index_by_school[school]
		activity_index_by_school[school] += 1
		values = {"admission_year": year}
		if row.get("status") == "Completed":
			metrics["completed_activities"] += 1
			lead_count = 24 + (index * 7) + (len(school) % 5)
			cost_million = 10 + (index % 5) * 4 + (len(school) % 3)
			values.update(
				attendance=lead_count + 12 + (index % 6),
				prospect_count=lead_count,
				contact_count=max(0, lead_count - 5),
				application_count=max(0, lead_count // 4),
				outcome="Positive" if index % 4 else "Follow-up Needed",
				next_action="Theo dõi hồ sơ sau hoạt động thực địa.",
				activity_cost=cost_million,
				activity_cost_unit="million_vnd",
				evidence_reference="demo:school-field-activity",
			)
		elif row.get("status") == "Planned":
			planned_date = now.date() + timedelta(days=7)
			forecast_min = 5 + (index % 4) * 3
			values.update(
				activity_date=planned_date,
				scheduled_datetime=datetime.combine(planned_date, time(8, 0)),
				expected_enrollment_min=forecast_min,
				expected_enrollment_max=forecast_min + 6,
				forecast_confidence=60 + (index % 4) * 7,
				forecast_sample_size=2 + (index % 5),
				forecast_source="historical-activity",
				evidence_reference="demo:historical-school-activity",
			)
			metrics["upcoming_plans"] += 1

		frappe.db.set_value("CRM School Activity", row["name"], values, update_modified=False)
		metrics["activities_updated"] += 1

		if row.get("status") != "Completed" or not frappe.db.table_exists("CRM Student Engagement Event"):
			continue
		students = students_by_school.get(school, [])
		# Keep attribution bounded and deterministic.  The activity's direct
		# prospect_count remains the observed fallback for any records not linked
		# to an append-only engagement event.
		selected = students[: min(len(students), 8 + index)]
		for student_index, student in enumerate(selected):
			try:
				from crm.fcrm.student_engagement_projection import project_student_engagement_event

				result = project_student_engagement_event(
					student=student["name"],
					event_type="School Activity",
					occurred_at=row.get("scheduled_datetime") or row.get("activity_date") or now,
					source_doctype="CRM School Activity",
					source_name=row["name"],
					values={"school_activity": row["name"]},
				)
				if result.get("replayed"):
					metrics["engagement_events_replayed"] += 1
				else:
					metrics["engagement_events_created"] += 1
				metrics["students_attributed"] += 1
				# Consent state is a projection fact, not a browser assertion.  Keep
				# one small unknown slice so the API exposes a partial-quality row too.
				frappe.db.set_value(
					"CRM Student Engagement Event",
					result["event"],
					"consent_state",
					"Unknown" if student_index % 5 == 0 else "Granted",
					update_modified=False,
				)
			except Exception as exc:
				metrics["errors"].append({"activity": row["name"], "student": student["name"], "error": str(exc)})

	return metrics


def _students_by_school(year: str, school_names: list[str]) -> dict[str, list[dict[str, Any]]]:
	if not school_names or not frappe.db.table_exists("CRM Student"):
		return {}
	rows = frappe.get_all(
		"CRM Student",
		filters={"admission_year": year, "high_school": ["in", school_names]},
		fields=["name", "high_school", "lifecycle_stage"],
		order_by="high_school asc, creation asc, name asc",
		limit_page_length=0,
	)
	result: dict[str, list[dict[str, Any]]] = defaultdict(list)
	for row in rows or []:
		if row.get("high_school") and row.get("name"):
			result[row["high_school"]].append(dict(row))
	return result
