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
	"execution",
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


def _execution_names_for_outcome_filters(*, recommendation=None, action=None, student=None) -> list[str] | None:
	"""Translate the legacy recommendation/action/student outcome filters into
	an execution-name filter: ``CRM Action Outcome`` carries no student/action/
	recommendation column of its own, only ``execution`` -> that links to
	``CRM Action Execution`` -> ``task`` (``CRM Action Item``, which does carry
	``student``/``action``).

	Returns ``None`` when none of these filters were requested (caller skips
	the join entirely); an empty list means the join matched nothing.
	"""
	if not (recommendation or action or student):
		return None
	execution_filters: dict = {}
	if recommendation:
		execution_filters["recommendation"] = recommendation
	if student or action:
		task_filters: dict = {}
		if student:
			task_filters["student"] = student
		if action:
			task_filters["action"] = action
		tasks = frappe.get_all("CRM Action Item", filters=task_filters, pluck="name")
		if not tasks:
			return []
		execution_filters["task"] = ["in", tasks]
	return frappe.get_all("CRM Action Execution", filters=execution_filters, pluck="name")


@frappe.whitelist()
def list_action_outcomes(execution=None, recommendation=None, action=None, student=None, start=0, page_length=20):
	"""List CRM Action Outcome rows (captured outcome evidence). Filter by
	execution, recommendation, action, or student (resolved through the
	execution/task join, since the outcome row itself only carries
	``execution``); paginated, newest first.
	"""
	filters = {}
	joined = _execution_names_for_outcome_filters(recommendation=recommendation, action=action, student=student)
	if joined is not None:
		if execution and execution not in joined:
			joined = []
		filters["execution"] = ["in", joined]
	elif execution:
		filters["execution"] = execution
	return paged_list(
		"CRM Action Outcome", OUTCOME_LIST_FIELDS,
		filters=filters, start=start, page_length=page_length, order_by="captured_at desc",
	)


@frappe.whitelist()
def get_action_outcome(name):
	"""Get one CRM Action Outcome by name, plus a resolvable ``OutcomeRef``
	drill-down: execution -> task -> student, re-checking the caller's Frappe
	read permission at each hop (the outcome/execution rows are readable by any
	Sale-family role, but the student behind them may be outside this caller's
	scope).
	"""
	row = _get("CRM Action Outcome", name)
	execution_name = row.get("execution")
	if not execution_name:
		return row
	execution = frappe.get_doc("CRM Action Execution", execution_name)
	execution.check_permission("read")
	task_name = execution.get("task")
	if not task_name:
		return row
	task = frappe.get_doc("CRM Action Item", task_name)
	task.check_permission("read")
	student = task.get("student")
	if not student:
		return row
	row["outcome_ref"] = build_outcome_ref(
		outcome_id=str(row.get("name")),
		subject=build_subject_ref("student", str(student), str(frappe.local.site or "frappe")),
		kind="verified_outcome",
		status=str(row.get("outcome_value") or row.get("outcome_type") or "recorded"),
		source_revision=str(execution_name),
		decision_id=str(execution.get("recommendation")) if execution.get("recommendation") else None,
		verified=True,
	)
	return row
