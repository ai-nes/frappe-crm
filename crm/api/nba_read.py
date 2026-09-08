"""Read-only listing/detail APIs for the NBA execution lifecycle.

CRM Recommendation, CRM Recommendation Feedback, CRM Action Execution,
CRM Action Execution Attempt and CRM Action Outcome are immutable,
service-managed aggregates (see their controllers) — they are created and
mutated only through the Phase 6 command service / crm.fcrm.nba, never
through a generic create/update/delete API. This module only exposes
list/get so callers can inspect them; write CRUD for CRM Action Type lives
in crm.api.action_type, and for CRM Action in crm.api.action.
"""

import frappe

from crm.api._pagination import paged_list
from crm.services.intelligence_refs import build_outcome_ref, build_subject_ref

RECOMMENDATION_LIST_FIELDS = [
	"name",
	"target_id",
	"action",
	"priority",
	"lifecycle_status",
	"decision_status",
	"execution_status",
	"channel",
	"confidence",
	"expected_impact",
	"rank",
	"evaluation",
	"expires_at",
	"recommended_at",
	"modified",
]

FEEDBACK_LIST_FIELDS = [
	"name",
	"feedback_id",
	"recommendation",
	"outcome",
	"student",
	"predicted_probability",
	"actual_result",
	"reward",
	"actual_impact",
	"feedback_source",
	"created_by",
	"created_at",
]

EXECUTION_LIST_FIELDS = [
	"name",
	"execution_id",
	"recommendation",
	"action",
	"student",
	"actor",
	"channel",
	"status",
	"scheduled_at",
	"started_at",
	"completed_at",
	"created_at",
]

EXECUTION_ATTEMPT_LIST_FIELDS = [
	"name",
	"action",
	"nba_execution",
	"actor",
	"operation",
	"status",
	"attempt_generation",
	"lease_count",
	"created_at",
]

OUTCOME_LIST_FIELDS = [
	"name",
	"outcome_id",
	"execution",
	"recommendation",
	"action",
	"student",
	"attempt",
	"outcome_type",
	"outcome_value",
	"success",
	"impact_score",
	"captured_by",
	"captured_at",
]


def _get(doctype, name):
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	return doc.as_dict()


@frappe.whitelist()
def list_recommendations(student=None, status=None, decision_status=None, execution_status=None, start=0, page_length=20):
	"""List CRM Recommendation rows (NBA advice). Filter by student, status
	(lifecycle_status), decision_status, or execution_status; paginated, newest
	first. ``student``/``status`` are the stable API parameter names; the
	underlying CRM Recommendation fields are ``target_id``/``lifecycle_status``.
	"""
	filters = {}
	if student:
		filters["target_id"] = student
	if status:
		filters["lifecycle_status"] = status
	if decision_status:
		filters["decision_status"] = decision_status
	if execution_status:
		filters["execution_status"] = execution_status
	return paged_list(
		"CRM Recommendation", RECOMMENDATION_LIST_FIELDS,
		filters=filters, start=start, page_length=page_length, order_by="recommended_at desc",
	)


@frappe.whitelist()
def get_recommendation(name):
	"""Get one CRM Recommendation by name."""
	return _get("CRM Recommendation", name)


@frappe.whitelist()
def list_recommendation_feedback(recommendation=None, student=None, start=0, page_length=20):
	"""List CRM Recommendation Feedback rows (predicted-vs-actual learning
	signal). Filter by recommendation or student; paginated, newest first.
	"""
	filters = {}
	if recommendation:
		filters["recommendation"] = recommendation
	if student:
		filters["student"] = student
	return paged_list(
		"CRM Recommendation Feedback", FEEDBACK_LIST_FIELDS,
		filters=filters, start=start, page_length=page_length, order_by="created_at desc",
	)


@frappe.whitelist()
def get_recommendation_feedback(name):
	"""Get one CRM Recommendation Feedback row by name."""
	return _get("CRM Recommendation Feedback", name)


@frappe.whitelist()
def list_action_executions(recommendation=None, action=None, student=None, status=None, start=0, page_length=20):
	"""List CRM Action Execution rows (provider execution projection). Filter
	by recommendation, action, student, or status; paginated, newest first.
	"""
	filters = {}
	if recommendation:
		filters["recommendation"] = recommendation
	if action:
		filters["action"] = action
	if student:
		filters["student"] = student
	if status:
		filters["status"] = status
	return paged_list(
		"CRM Action Execution", EXECUTION_LIST_FIELDS,
		filters=filters, start=start, page_length=page_length, order_by="created_at desc",
	)


@frappe.whitelist()
def get_action_execution(name):
	"""Get one CRM Action Execution by name."""
	return _get("CRM Action Execution", name)


@frappe.whitelist()
def list_action_execution_attempts(action=None, nba_execution=None, status=None, start=0, page_length=20):
	"""List CRM Action Execution Attempt rows (per-retry identity/state fence).
	Filter by action, nba_execution, or status; paginated, newest first.
	System Manager only.
	"""
	filters = {}
	if action:
		filters["action"] = action
	if nba_execution:
		filters["nba_execution"] = nba_execution
	if status:
		filters["status"] = status
	return paged_list(
		"CRM Action Execution Attempt", EXECUTION_ATTEMPT_LIST_FIELDS,
		filters=filters, start=start, page_length=page_length, order_by="created_at desc",
	)


@frappe.whitelist()
def get_action_execution_attempt(name):
	"""Get one CRM Action Execution Attempt by name. System Manager only."""
	return _get("CRM Action Execution Attempt", name)


@frappe.whitelist()
def list_action_outcomes(execution=None, recommendation=None, action=None, student=None, start=0, page_length=20):
	"""List CRM Action Outcome rows (captured outcome evidence). Filter by
	execution, recommendation, action, or student; paginated, newest first.
	"""
	filters = {}
	if execution:
		filters["execution"] = execution
	if recommendation:
		filters["recommendation"] = recommendation
	if action:
		filters["action"] = action
	if student:
		filters["student"] = student
	return paged_list(
		"CRM Action Outcome", OUTCOME_LIST_FIELDS,
		filters=filters, start=start, page_length=page_length, order_by="captured_at desc",
	)


@frappe.whitelist()
def get_action_outcome(name):
	"""Get one CRM Action Outcome by name."""
	row = _get("CRM Action Outcome", name)
	student = row.get("student")
	if student:
		row["outcome_ref"] = build_outcome_ref(
			outcome_id=str(row.get("outcome_id") or row.get("name")),
			subject=build_subject_ref("student", str(student), str(frappe.local.site or "frappe")),
			kind="verified_outcome",
			status=str(row.get("outcome_type") or "recorded"),
			source_revision=str(row.get("name") or "outcome"),
			decision_id=str(row.get("recommendation")) if row.get("recommendation") else None,
			verified=True,
		)
	return row
