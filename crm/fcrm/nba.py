"""Server services for the CRM Next Best Action contract."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.fcrm.action_type_catalog import (
	ACTION_TYPE_CODES,
	LEGACY_ACTION_TYPE_ALIASES,
	LEGACY_RECOMMENDATION_ONLY,
	canonicalize_action_type,
)
from crm.fcrm.action_type_registry import is_available_action_type
from crm.fcrm.nba_timing import resolve_scheduled_at

# ACTION_TYPES is the canonical 79-code catalog. Legacy values are kept
# separate so callers can distinguish catalog rows from compatibility aliases.
ACTION_TYPES = ACTION_TYPE_CODES
LEGACY_ACTION_TYPES = LEGACY_ACTION_TYPE_ALIASES | LEGACY_RECOMMENDATION_ONLY
DEFAULT_CHANNEL_BY_ACTION = {
	"CALL": "CALL",
	"EMAIL": "EMAIL",
	"MESSAGE": "MESSAGE",
	"PARENT_CONTACT": "CALL",
}
APPROVAL_ACTIONS = frozenset({"EMAIL", "MESSAGE", "PARENT_CONTACT", "HANDOFF"})
ALLOWED_ACTORS = ["Sale", "Lead Sales", "Admissions Director"]
SUPPORTED_CHANNELS = frozenset({"NONE", "CALL", "EMAIL", "MESSAGE"})
FEEDBACK_SOURCES = frozenset({"human", "provider", "system", "analytics"})
SCORE_MIN = -1.0
SCORE_MAX = 1.0
ACTION_DEFINITION_DOCTYPE = "CRM Action"
ACTION_ITEM_DOCTYPE = "CRM Action Item"
TIMING_POLICY_DOCTYPE = "CRM Timing Policy"
ACTION_EXECUTION_DOCTYPE = "CRM Action Execution"
ACTION_OUTCOME_DOCTYPE = "CRM Action Outcome"
RECOMMENDATION_FEEDBACK_DOCTYPE = "CRM Recommendation Feedback"


def _doctype_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.exists("DocType", doctype))
	except Exception:
		return False


def _service_insert(values: dict[str, Any]):
	previous = getattr(frappe.flags, "nba_service_write", False)
	frappe.flags.nba_service_write = True
	try:
		return frappe.get_doc(values).insert(ignore_permissions=True)
	finally:
		frappe.flags.nba_service_write = previous


def _json(value: Any) -> str:
	return json.dumps(
		value if value is not None else {}, ensure_ascii=False, separators=(",", ":"), default=str
	)


def _digest(value: Any) -> str:
	return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _bounded_number(value: Any, field: str, *, minimum: float = SCORE_MIN, maximum: float = SCORE_MAX):
	if value in (None, ""):
		return None
	try:
		result = float(value)
	except (TypeError, ValueError):
		frappe.throw(f"{field} must be numeric.", frappe.ValidationError)
		return None
	if not minimum <= result <= maximum:
		frappe.throw(
			f"{field} must be between {minimum:g} and {maximum:g}.", frappe.ValidationError
		)
	return result


def get_nba_action_definition(action):
	"""Return the catalog Action linked to a work item or recommendation."""
	definition_name = None
	if action:
		definition_name = action.get("action") or action.get("nba_action")
	if not definition_name or not _doctype_exists(ACTION_DEFINITION_DOCTYPE):
		return None
	return frappe.get_doc(ACTION_DEFINITION_DOCTYPE, definition_name)


def nba_action_allowed_actors(definition) -> set[str]:
	if not definition:
		return set(ALLOWED_ACTORS)
	try:
		actors = json.loads(definition.get("allowed_actors") or "[]")
	except (TypeError, ValueError):
		frappe.throw("Action Definition allowed_actors is not valid JSON.", frappe.ValidationError)
	return {str(actor) for actor in actors if actor}


def resolve_nba_channel(action, channel: str | None = None) -> str:
	"""Resolve an explicit channel or the configured Action Definition default."""
	definition = get_nba_action_definition(action)
	resolved = channel or (definition.get("default_channel") if definition else None)
	resolved = str(resolved or DEFAULT_CHANNEL_BY_ACTION.get(action.get("action_type") or "", "NONE"))
	if resolved not in SUPPORTED_CHANNELS:
		frappe.throw("Unsupported NBA channel.", frappe.ValidationError)
	return resolved


def validate_nba_action_execution(action, *, actor: str | None = None, operation: str | None = None):
	"""Enforce the configured Action Definition policy at the execution boundary."""
	definition = get_nba_action_definition(action)
	if not definition:
		return None
	if not definition.get("enabled"):
		frappe.throw("This Action Definition is disabled.", frappe.PermissionError, title="ACTION_DEFINITION_DISABLED")
	actor = actor or frappe.session.user
	actor_roles = set(frappe.get_roles(actor)) if actor and actor != "Administrator" else {"System Manager"}
	if actor != "Administrator" and "System Manager" not in actor_roles:
		allowed_actors = nba_action_allowed_actors(definition)
		if not actor_roles.intersection(allowed_actors):
			frappe.throw(
				"Actor is not allowed to execute this Action Definition.",
				frappe.PermissionError,
				title="ACTION_ACTOR_NOT_ALLOWED",
			)
	if operation in {"DISPATCH", "SCHEDULE", "RECORD_OUTCOME"}:
		if action.get("state") not in {"accepted", "in-progress"}:
			frappe.throw(
				"The Action must be accepted before execution.",
				frappe.PermissionError,
				title="ACTION_APPROVAL_REQUIRED",
			)
		if definition.get("requires_approval") and action.get("requires_review"):
			frappe.throw(
				"This Action is waiting for approval.",
				frappe.PermissionError,
				title="ACTION_APPROVAL_REQUIRED",
			)
	return definition


def get_nba_timing_policy(policy_name: str | None):
	if not policy_name:
		return None
	if not _doctype_exists(TIMING_POLICY_DOCTYPE):
		frappe.throw("CRM Timing Policy is not installed.", frappe.ValidationError)
	return frappe.get_doc(TIMING_POLICY_DOCTYPE, policy_name)


def resolve_nba_schedule(action, scheduled_at: Any = None):
	"""Resolve one schedule request from the Recommendation's Timing Policy."""
	recommendation_name = action.get("recommendation")
	policy_name = (
		frappe.db.get_value("CRM Recommendation", recommendation_name, "timing_policy")
		if recommendation_name and _doctype_exists("CRM Recommendation")
		else None
	)
	policy = get_nba_timing_policy(policy_name)
	if not policy:
		if scheduled_at in (None, ""):
			frappe.throw("scheduled_at is required when no CRM Timing Policy is configured.", frappe.ValidationError)
		try:
			return resolve_scheduled_at({"trigger_type": "schedule"}, scheduled_at, now=now_datetime())
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError, title="TIMING_POLICY_INVALID")
	recommendation_trigger = (
		frappe.db.get_value("CRM Recommendation", recommendation_name, "trigger")
		if recommendation_name
		else None
	)
	if (
		policy.get("trigger_type") == "event"
		and policy.get("trigger_event")
		and recommendation_trigger
		and policy.trigger_event != recommendation_trigger
	):
		frappe.throw("Recommendation trigger does not match the CRM Timing Policy event.", frappe.ValidationError)
	try:
		return resolve_scheduled_at(policy.as_dict(), scheduled_at or None, now=now_datetime())
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError, title="TIMING_POLICY_INVALID")


def ensure_nba_action(action_type: str | None) -> str | None:
	"""Return the canonical CRM Action catalog name for an allowlisted code."""
	if not is_available_action_type(action_type):
		return None
	return canonicalize_action_type(action_type)


def ensure_nba_recommendation(
	*,
	student: str,
	action_type: str | None,
	objective: str | None,
	evidence: Any,
	priority: str,
	due_at: Any,
	expires_at: Any,
	owner: str | None = None,
	trigger: str | None = None,
	timing_policy: str | None = None,
	recommended_at: Any = None,
	confidence: float | None = None,
	expected_impact: float | None = None,
	model: str | None = None,
	model_version: str | None = None,
):
	"""Create-or-return one recommendation using only the public contract fields."""
	action_type = canonicalize_action_type(action_type)
	if not _doctype_exists("CRM Recommendation"):
		return None
	action_name = ensure_nba_action(action_type)
	definition = get_nba_action_definition({"action": action_name}) if action_name else None
	if confidence is not None:
		confidence = _bounded_number(confidence, "confidence", minimum=0.0, maximum=1.0)
	if expected_impact is not None:
		expected_impact = _bounded_number(expected_impact, "expected_impact")
	if timing_policy:
		get_nba_timing_policy(timing_policy)
	recommended_at = recommended_at or now_datetime()
	payload = [
		"CRM Student",
		student,
		action_name,
		objective,
		evidence,
		priority,
		due_at,
		expires_at,
		owner,
		trigger,
		timing_policy,
		recommended_at,
		confidence,
		expected_impact,
		model,
		model_version,
	]
	recommendation_id = "REC-" + _digest(payload)[:24]
	existing = frappe.db.get_value(
		"CRM Recommendation", {"recommendation_id": recommendation_id}, "name"
	)
	if existing:
		return frappe.get_doc("CRM Recommendation", existing)
	return _service_insert(
		{
			"doctype": "CRM Recommendation",
			"recommendation_id": recommendation_id,
			"target_type": "CRM Student",
			"target_id": student,
			"action": action_name,
			"purpose": objective or "Follow up on the next-best action.",
			"channel": resolve_nba_channel(
				{"action_type": action_type, "nba_action": action_name},
				definition.get("default_channel") if definition else None,
			),
			"trigger": trigger or action_type or "recommendation",
			"reason": objective or "Generated from the Student decision context.",
			"evidence": evidence if evidence is not None else [],
			"priority": priority if priority in {"high", "medium", "low"} else "medium",
			"confidence": confidence,
			"expected_impact": expected_impact,
			"timing_policy": timing_policy,
			"recommended_at": recommended_at,
			"expires_at": expires_at,
			"owner": owner,
			"lifecycle_status": "proposed",
			"decision_status": "pending",
			"execution_status": "not_started",
			"model": model,
			"model_version": model_version,
		}
	)


def sync_nba_recommendation_for_action(action) -> None:
	"""Project current Action state into the Recommendation contract statuses."""
	recommendation_name = action.get("recommendation")
	if not recommendation_name or not _doctype_exists("CRM Recommendation"):
		return
	decision_status = {
		"pending": "pending",
		"requires-review": "pending",
		"accepted": "accepted",
		"in-progress": "accepted",
		"completed": "accepted",
		"deferred": "deferred",
		"rejected": "rejected",
		"cancelled": "accepted",
		"superseded": "accepted",
	}.get(str(action.get("state") or "pending"), "pending")
	execution_status = {
		"planned": "not_started",
		"in_progress": "in_progress",
		"completed": "completed",
		"failed": "failed",
		"cancelled": "cancelled",
	}.get(str(action.get("execution_status") or "planned"), "not_started")
	lifecycle_status = {
		"superseded": "superseded",
		"completed": "completed",
		"cancelled": "cancelled",
		"rejected": "expired",
	}.get(action.get("state"), "active")
	frappe.db.set_value(
		"CRM Recommendation",
		recommendation_name,
		{
			"decision_status": decision_status,
			"execution_status": execution_status,
			"lifecycle_status": lifecycle_status,
			"owner": action.get("action_owner"),
		},
		update_modified=False,
	)


def ensure_nba_execution_for_attempt(
	attempt, action=None, *, channel: str | None = None, scheduled_at: Any = None, input_payload: Any = None
):
	"""Create the Action Execution projection for an Action attempt."""
	if not _doctype_exists(ACTION_EXECUTION_DOCTYPE):
		return None
	action = action or frappe.get_doc(ACTION_ITEM_DOCTYPE, attempt.action)
	recommendation = action.get("recommendation")
	if not recommendation:
		return None
	resolve_nba_channel(action, channel)
	existing_name = attempt.get("nba_execution")
	status = {
		"pending": "pending",
		"queued": "queued",
		"confirmed": "in_progress",
		"failed": "failed",
		"cancelled": "cancelled",
	}.get(str(attempt.status), "pending")
	values = {
		"recommendation": recommendation,
		"actor": attempt.actor,
		"channel": resolve_nba_channel(action, channel),
		"scheduled_at": scheduled_at,
		"status": status,
		"input": input_payload
		if input_payload is not None
		else {
			"operation": attempt.operation,
			"action_revision": attempt.action_revision,
			"package_revision": attempt.package_revision,
		},
	}
	if existing_name:
		execution = frappe.get_doc(ACTION_EXECUTION_DOCTYPE, existing_name)
		from crm.fcrm.doctype.crm_action_execution.crm_action_execution import TRANSITIONS

		updates = {
			key: value
			for key, value in values.items()
			if key not in {"recommendation", "actor", "status"} and value is not None
		}
		if status == execution.status or status in TRANSITIONS.get(execution.status, set()):
			updates["status"] = status
		if updates:
			frappe.db.set_value(ACTION_EXECUTION_DOCTYPE, existing_name, updates, update_modified=False)
		execution.reload()
		return execution
	execution = _service_insert({"doctype": ACTION_EXECUTION_DOCTYPE, **values})
	if attempt.get("name"):
		frappe.db.set_value(
			"CRM Action Execution Attempt", attempt.name, "nba_execution", execution.name, update_modified=False
		)
	return execution


def update_nba_execution(
	attempt_id: str,
	*,
	status: str | None = None,
	channel: str | None = None,
	scheduled_at: Any = None,
	started_at: Any = None,
	completed_at: Any = None,
	input_payload: Any = None,
	output: Any = None,
	error: str | None = None,
):
	"""Update the server-owned execution projection fields."""
	if not _doctype_exists(ACTION_EXECUTION_DOCTYPE):
		return None
	attempt = frappe.get_doc("CRM Action Execution Attempt", attempt_id)
	execution = ensure_nba_execution_for_attempt(
		attempt, channel=channel, scheduled_at=scheduled_at, input_payload=input_payload
	)
	if not execution:
		return None
	values = {}
	if status:
		values["status"] = status
	if channel:
		values["channel"] = channel
	if scheduled_at is not None:
		values["scheduled_at"] = scheduled_at
	if started_at is not None:
		values["started_at"] = started_at
	if completed_at is not None:
		values["completed_at"] = completed_at
	if input_payload is not None:
		values["input"] = input_payload
	if output is not None:
		values["output"] = output
	if error is not None:
		values["error"] = str(error)[:2000]
	if values:
		from crm.fcrm.doctype.crm_action_execution.crm_action_execution import TRANSITIONS

		if (
			"status" in values
			and values["status"] != execution.status
			and values["status"] not in TRANSITIONS.get(execution.status, set())
		):
			values.pop("status")
		if values:
			frappe.db.set_value(ACTION_EXECUTION_DOCTYPE, execution.name, values, update_modified=False)
		execution.reload()
	_sync_nba_recommendation_execution(execution, scheduled_at=scheduled_at)
	return frappe.get_doc(ACTION_EXECUTION_DOCTYPE, execution.name)


def record_nba_outcome_for_action(
	action,
	*,
	status: str,
	outcome_code: str | None = None,
	attempt_id: str | None = None,
	notes: str | None = None,
	actor: str | None = None,
	impact_score: float | None = None,
):
	"""Create one immutable Action Outcome for a terminal Action transition."""
	if not _doctype_exists(ACTION_OUTCOME_DOCTYPE):
		return None
	impact_score = _bounded_number(impact_score, "impact_score")
	execution_name = None
	if attempt_id:
		execution_name = frappe.db.get_value("CRM Action Execution Attempt", attempt_id, "nba_execution")
	if not execution_name and action.get("recommendation"):
		rows = frappe.get_all(
			ACTION_EXECUTION_DOCTYPE,
			filters={"recommendation": action.recommendation},
			fields=["name"],
			order_by="creation desc",
			limit_page_length=1,
		)
		execution_name = rows[0].name if rows else None
	if not execution_name:
		return None
	existing = frappe.db.get_value(
		ACTION_OUTCOME_DOCTYPE,
		{"execution": execution_name, "outcome_type": "action_execution"},
		"name",
	)
	if existing:
		return frappe.get_doc(ACTION_OUTCOME_DOCTYPE, existing)
	outcome = _service_insert(
		{
			"doctype": ACTION_OUTCOME_DOCTYPE,
			"execution": execution_name,
			"outcome_type": "action_execution",
			"outcome_value": outcome_code or status,
			"success": 1 if status == "completed" else 0,
			"impact_score": impact_score,
			"captured_by": actor or frappe.session.user,
			"captured_at": now_datetime(),
			"notes": notes,
		}
	)
	if attempt_id:
		update_nba_execution(
			attempt_id,
			status={"completed": "completed", "failed": "failed", "cancelled": "cancelled"}.get(
				status, "in_progress"
			),
			completed_at=outcome.captured_at if status in {"completed", "failed", "cancelled"} else None,
			output={"outcome": outcome_code} if outcome_code else None,
		)
	else:
		frappe.db.set_value(
			ACTION_EXECUTION_DOCTYPE,
			execution_name,
			{
				"status": {"completed": "completed", "failed": "failed", "cancelled": "cancelled"}.get(
					status, "in_progress"
				),
				"completed_at": outcome.captured_at
				if status in {"completed", "failed", "cancelled"}
				else None,
				"output": {"outcome": outcome_code} if outcome_code else None,
			},
			update_modified=False,
		)
	return outcome


def _sync_nba_recommendation_execution(execution, *, scheduled_at: Any = None):
	"""Keep the Recommendation execution status projection current."""
	if not execution.recommendation or not _doctype_exists("CRM Recommendation"):
		return
	if scheduled_at is not None:
		execution_status = "scheduled"
	else:
		execution_status = {
			"pending": "not_started",
			"queued": "scheduled",
			"in_progress": "in_progress",
			"completed": "completed",
			"failed": "failed",
			"cancelled": "cancelled",
		}.get(execution.status, "not_started")
	frappe.db.set_value(
		"CRM Recommendation",
		execution.recommendation,
		"execution_status",
		execution_status,
		update_modified=False,
	)


def record_nba_feedback(
	*,
	recommendation: str,
	outcome: str,
	predicted_probability: float,
	actual_result: str,
	reward: float | None,
	actual_impact: float | None,
	feedback_source: str,
):
	"""Create one immutable feedback row using only the public contract fields."""
	if not _doctype_exists(RECOMMENDATION_FEEDBACK_DOCTYPE):
		frappe.throw("CRM Recommendation Feedback is not installed.", frappe.ValidationError)
	if predicted_probability in (None, ""):
		frappe.throw("predicted_probability is required.", frappe.ValidationError)
	if actual_result in (None, ""):
		frappe.throw("actual_result is required.", frappe.ValidationError)
	if feedback_source not in FEEDBACK_SOURCES:
		frappe.throw("Invalid feedback source.", frappe.ValidationError)
	predicted_probability = _bounded_number(
		predicted_probability, "predicted_probability", minimum=0.0, maximum=1.0
	)
	reward = _bounded_number(reward, "reward")
	actual_impact = _bounded_number(actual_impact, "actual_impact")
	return _service_insert(
		{
			"doctype": RECOMMENDATION_FEEDBACK_DOCTYPE,
			"recommendation": recommendation,
			"outcome": outcome,
			"predicted_probability": predicted_probability,
			"actual_result": str(actual_result)[:500],
			"reward": reward,
			"actual_impact": actual_impact,
			"feedback_source": feedback_source,
			"created_at": now_datetime(),
		}
	)
