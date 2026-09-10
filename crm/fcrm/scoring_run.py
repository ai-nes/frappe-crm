"""Frappe-local scoring orchestration and scheduled cohort entry point."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

import frappe
from frappe.utils import now_datetime

from crm.api.scoring_write import append_score_if_current
from crm.fcrm.scoring_engine import score_components
from crm.fcrm.scoring_policy import get_active_policy

_MAX_CONTRIBUTORS = 60
_SCORER_LOOKBACK_DAYS = 180


def _bounded_contributors(details: Iterable[dict]) -> list[dict]:
	"""Collapse repeated hits and keep the persisted detail contract bounded.

	Repeated interactions for one rule are one explainability signal, not a
	reason to make the whole authoritative score write fail.  If a policy still
	produces more than the wire limit after collapsing repeated signals, the
	deterministic tail is folded into the last retained real signal and its
	reason records that aggregation.
	"""
	grouped: list[dict] = []
	by_key: dict[tuple[str, str, str], dict] = {}
	for detail in details:
		key = (detail["category"], detail["rule_id"], detail["signal"])
		current = by_key.get(key)
		if current is None:
			current = dict(detail)
			by_key[key] = current
			grouped.append(current)
		else:
			current["score"] += detail["score"]
	if len(grouped) <= _MAX_CONTRIBUTORS:
		return grouped
	retained = grouped[: _MAX_CONTRIBUTORS - 1]
	overflow = grouped[_MAX_CONTRIBUTORS - 1 :]
	bucket = dict(overflow[0])
	bucket["score"] = sum(row["score"] for row in overflow)
	bucket["reason"] = (
		f"{bucket.get('reason') or ''} Aggregated {len(overflow)} additional contributors."
	).strip()[:240]
	return [*retained, bucket]


def _as_dict(row) -> dict:
	return row.as_dict() if hasattr(row, "as_dict") else dict(row)


def _scoring_since_date(reference_date: datetime) -> str:
	"""Preserve the retired scorer's bounded rule-input window.

	Aggregate recency deliberately reads uncapped history in
	``days_since_student_touchpoint``; rule hits remain limited to the former
	180-day scoring window so the ownership move does not change Fit,
	Engagement, Intent, or Negative behavior accidentally.
	"""
	return (reference_date - timedelta(days=_SCORER_LOOKBACK_DAYS)).strftime("%Y-%m-%d")


def _student_rows(student_doc) -> tuple[list[dict], list[dict]]:
	academic = [_as_dict(row) for row in (student_doc.get("academic_results") or [])]
	language = [_as_dict(row) for row in (student_doc.get("language_certificates") or [])]
	if not academic:
		academic = [
			_as_dict(row)
			for row in frappe.get_all(
				"CRM Student Academic Result",
				filters={"parent": student_doc.name, "parenttype": "CRM Student"},
				fields=["school_year", "grade", "academic_rank", "gpa"],
				order_by="idx asc",
			)
		]
	if not language:
		language = [
			_as_dict(row)
			for row in frappe.get_all(
				"CRM Student Language Certificate",
				filters={"parent": student_doc.name, "parenttype": "CRM Student"},
				fields=["language", "certificate_name", "score_level", "issue_date", "expiry_date"],
				order_by="idx asc",
			)
		]
	return academic, language


def _student_interactions(student: str, *, since_date: str) -> list[dict]:
	rows = frappe.get_all(
		"CRM Interaction",
		filters={"student": student, "interaction_datetime": [">=", since_date]},
		fields=["name", "interaction_type", "interaction_datetime", "outcome", "direction"],
		order_by="interaction_datetime asc, name asc",
		limit_page_length=0,
	)
	for row in rows:
		row["interaction_semantic_key"] = row.get("interaction_type")
	return rows


def _student_intents(student: str, *, since_date: str) -> list[dict]:
	rows = frappe.get_all(
		"CRM Intent",
		filters={"student": student, "creation": [">=", since_date]},
		fields=[
			"name",
			"intent_type",
			"intent_role",
			"importance",
			"polarity",
			"confidence",
			"interaction",
			"creation",
		],
		order_by="creation asc, name asc",
		limit_page_length=0,
	)
	interaction_names = sorted({row.get("interaction") for row in rows if row.get("interaction")})
	interaction_dates = {}
	if interaction_names:
		interaction_dates = {
			row["name"]: row.get("interaction_datetime")
			for row in frappe.get_all(
				"CRM Interaction",
				filters={"name": ["in", interaction_names]},
				fields=["name", "interaction_datetime"],
				limit_page_length=0,
			)
		}
	for row in rows:
		row["interaction_date"] = interaction_dates.get(row.get("interaction"))
		row["intent_semantic_key"] = row.get("intent_type")
	return rows


def enqueue_score_student(student: str, *, triggered_by: str = "event", revision: int | None = None) -> str:
	"""Queue one scoring calculation after its source transaction commits."""
	if not student:
		return ""
	job = frappe.enqueue(
		"crm.fcrm.scoring_run.score_student",
		queue="short",
		enqueue_after_commit=True,
		student=student,
		triggered_by=triggered_by,
		source_revision=revision,
	)
	return getattr(job, "name", "") or "queued"


def score_student(
	student: str,
	*,
	now: datetime | None = None,
	triggered_by: str = "event",
	triggered_by_doctype: str = "",
	triggered_by_name: str = "",
	source_revision: int | None = None,
) -> dict:
	"""Compute and persist one student's score through the Phase 1 CAS command."""
	student_doc = frappe.get_doc("CRM Student", student)
	reference_date = now or now_datetime()
	policy = get_active_policy(as_of=reference_date)
	if not policy:
		return {"student": student, "skipped": True, "reason": "no_active_policy"}
	since_date = _scoring_since_date(reference_date)
	academic_results, language_certs = _student_rows(student_doc)
	components = score_components(
		student=student_doc,
		academic_results=academic_results,
		language_certs=language_certs,
		interactions=_student_interactions(student, since_date=since_date),
		intents=_student_intents(student, since_date=since_date),
		policy=policy,
		reference_date=reference_date,
	)
	all_details = []
	for result in components.values():
		all_details.extend(result.details)
	negative = components["negative"]
	bounded_details = _bounded_contributors(all_details)
	bounded_negative_details = _bounded_contributors(negative.details)
	payload = {
		"student": student,
		"source_score_input_revision": (
			int(student_doc.score_input_revision or 0) if source_revision is None else int(source_revision)
		),
		"policy_revision": int(policy["policy_revision"]),
		"policy_hash": policy["policy_hash"],
		"score_template": policy["template_id"],
		"scoring_time": reference_date.strftime("%Y-%m-%d %H:%M:%S"),
		"fit_score": components["fit"].score,
		"engagement_score": components["engagement"].score,
		"intent_score": components["intent"].score,
		"negative_score": negative.score,
		"details": bounded_details,
		"components": {
			"fit": components["fit"].score,
			"engagement": components["engagement"].score,
			"intent": components["intent"].score,
			"negative": {"score": negative.score, "contributors": bounded_negative_details},
		},
	}
	if triggered_by_doctype:
		payload["triggered_by_doctype"] = triggered_by_doctype
		payload["triggered_by"] = triggered_by_name
	previous_flag = getattr(frappe.flags, "crm_internal_scoring", False)
	frappe.flags.crm_internal_scoring = True
	try:
		result = append_score_if_current(**payload)
	finally:
		frappe.flags.crm_internal_scoring = previous_flag
	return {"student": student, **result}


def score_active_cohort(limit: int = 500) -> dict:
	"""Enqueue one score job per active Student as the Frappe scheduler backstop."""
	page_size = min(max(int(limit), 1), 1000)
	closed_statuses = frappe.get_all(
		"CRM Enrollment Status",
		filters={"stage_category": ["in", ["enrolled", "lost"]], "enabled": 1},
		pluck="name",
		limit_page_length=100,
	)
	if not closed_statuses:
		frappe.throw(
			"Cannot score the active cohort because no enrolled/lost enrollment statuses are configured.",
			frappe.ValidationError,
		)
	queued = 0
	last_name = None
	while True:
		filters = {"enrollment_status": ["not in", closed_statuses]}
		if last_name:
			filters["name"] = [">", last_name]
		students = frappe.get_all(
			"CRM Student",
			filters=filters,
			pluck="name",
			order_by="name asc",
			limit_page_length=page_size,
		)
		if not students:
			break
		for student in students:
			enqueue_score_student(student, triggered_by="batch")
			queued += 1
		if len(students) < page_size:
			break
		last_name = students[-1]
	return {"queued": queued, "closed_statuses": len(closed_statuses)}
