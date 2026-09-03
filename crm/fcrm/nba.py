"""Compatibility bridge for the explicit CRM recommendation/action records.

The existing CRM Recommendation/Action aggregates remain authoritative for
operator decisions. This module creates deterministic projections around them
without a destructive rename or a second decision engine.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.fcrm.nba_timing import resolve_scheduled_at

ACTION_TYPES = frozenset(
	{
		"CALL",
		"EMAIL",
		"MESSAGE",
		"COUNSELING",
		"MEETING",
		"EVENT_INVITE",
		"CAMPUS_VISIT",
		"DOCUMENT_REQUEST",
		"APPLICATION_SUPPORT",
		"PARENT_CONTACT",
		"HANDOFF",
		"WAIT",
		"FOLLOW_UP",
	}
)
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
ACTION_DEFINITION_DOCTYPE = "CRM Action Definition"
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
	"""Return the Action Definition linked to an Action, when available."""
	definition_name = action.get("nba_action") if action else None
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
		frappe.throw("CRM Timing Policy is not migrated.", frappe.ValidationError)
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
	"""Return a catalog definition for an allowlisted Action type."""
	if not action_type or action_type not in ACTION_TYPES or not _doctype_exists(ACTION_DEFINITION_DOCTYPE):
		return None
	existing = frappe.db.get_value(ACTION_DEFINITION_DOCTYPE, {"code": action_type}, "name")
	if existing:
		return existing
	return _service_insert(
		{
			"doctype": ACTION_DEFINITION_DOCTYPE,
			"code": action_type,
			"description": f"Canonical CRM action type: {action_type}.",
			"purpose": f"Execute the {action_type.lower().replace('_', ' ')} action.",
			"default_channel": DEFAULT_CHANNEL_BY_ACTION.get(action_type, "NONE"),
			"allowed_actors": _json(ALLOWED_ACTORS),
			"requires_approval": 1 if action_type in APPROVAL_ACTIONS else 0,
			"auto_execute": 0,
			"enabled": 1,
		}
	).name


def ensure_nba_recommendation(
	*,
	student: str,
	action_type: str | None,
	objective: str | None,
	evidence: Any,
	priority: str,
	due_at: Any,
	expires_at: Any,
	generation_idempotency_key: str,
	producer_identity: str,
	payload_digest: str,
	source_context_revision: int,
	source_stage_key: str | None,
	policy_version: str | None,
	owner: str | None = None,
	trigger: str | None = None,
	timing_policy: str | None = None,
	recommended_at: Any = None,
	confidence: float | None = None,
	expected_impact: float | None = None,
	model: str | None = None,
	model_version: str | None = None,
):
	"""Create-or-return the CRM Recommendation NBA projection."""
	if not _doctype_exists("CRM Recommendation"):
		return None
	action_name = ensure_nba_action(action_type)
	definition = get_nba_action_definition({"nba_action": action_name}) if action_name else None
	if confidence is not None:
		confidence = _bounded_number(confidence, "confidence", minimum=0.0, maximum=1.0)
	if expected_impact is not None:
		expected_impact = _bounded_number(expected_impact, "expected_impact")
	if timing_policy:
		get_nba_timing_policy(timing_policy)
	source_key = source_stage_key or generation_idempotency_key
	condition_version = max(int(source_context_revision or 0), 1)
	context_hash = payload_digest or _digest(
		[student, source_key, action_type, objective, evidence, priority, due_at]
	)
	existing = frappe.db.get_value(
		"CRM Recommendation",
		{
			"student": student,
			"rule_key": "nba_v2",
			"source_intent_id": source_key,
			"condition_version": condition_version,
			"context_hash": context_hash,
		},
		"name",
	)
	if existing:
		return frappe.get_doc("CRM Recommendation", existing)

	recommendation = _service_insert(
		{
			"doctype": "CRM Recommendation",
			"student": student,
			"rule_key": "nba_v2",
			"source_intent_id": source_key,
			"condition_version": condition_version,
			"context_hash": context_hash,
			"policy_version": policy_version or "nba-v2",
			"producer_id": producer_identity,
			"producer_revision": 1,
			"priority": priority if priority in {"high", "medium", "low"} else "medium",
			"status": "new",
			"expires_at": expires_at,
			"created_at": now_datetime(),
			"recommended_at": recommended_at or now_datetime(),
			"recommended_timing": due_at,
			"recommended_action": action_type,
			"action": action_name,
			"target_type": "CRM Student",
			"target_id": student,
			"purpose": objective or "Follow up on the next-best action.",
			"channel": resolve_nba_channel(
				{"action_type": action_type, "nba_action": action_name},
				definition.get("default_channel") if definition else None,
			),
			"trigger": trigger or source_key,
			"reason": objective or "Generated from the Student decision context.",
			"evidence": evidence if evidence is not None else [],
			"confidence": confidence,
			"expected_impact": expected_impact,
			"timing_policy": timing_policy,
			"owner": owner,
			"lifecycle_status": "proposed",
			"decision_status": "pending",
			"execution_status": "not_started",
			"model": model,
			"model_version": model_version,
		}
	)
	return recommendation


def sync_nba_recommendation_for_action(action) -> None:
	"""Project current Action state into Recommendation NBA status fields."""
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
	"""Create the Action Execution projection for an AI-backed Action attempt."""
	if not _doctype_exists(ACTION_EXECUTION_DOCTYPE):
		return None
	action = action or frappe.get_doc("CRM Action", attempt.action)
	recommendation = action.get("recommendation")
	if not recommendation:
		return None
	resolve_nba_channel(action, channel)
	existing = frappe.db.get_value(ACTION_EXECUTION_DOCTYPE, {"attempt": attempt.name}, "name")
	status = {
		"pending": "pending",
		"queued": "queued",
		"confirmed": "in_progress",
		"failed": "failed",
		"cancelled": "cancelled",
	}.get(str(attempt.status), "pending")
	values = {
		"recommendation": recommendation,
		"action": action.name,
		"student": action.student,
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
		"attempt": attempt.name,
		"provider_event_id": attempt.get("provider_event_id"),
		"idempotency_key": f"nba-execution:{attempt.name}",
		"created_at": attempt.get("created_at") or now_datetime(),
	}
	if existing:
		execution = frappe.get_doc(ACTION_EXECUTION_DOCTYPE, existing)
		from crm.fcrm.doctype.crm_action_execution.crm_action_execution import TRANSITIONS

		updates = {
			key: value
			for key, value in values.items()
			if key not in {"recommendation", "action", "student", "actor", "created_at", "status"}
			and value is not None
		}
		desired_status = values["status"]
		if desired_status == execution.status or desired_status in TRANSITIONS.get(execution.status, set()):
			updates["status"] = desired_status
		if updates:
			frappe.db.set_value(ACTION_EXECUTION_DOCTYPE, existing, updates, update_modified=False)
		execution.reload()
		return execution
	values["execution_id"] = "NBA-EXE-" + hashlib.sha256(attempt.name.encode()).hexdigest()[:24]
	return _service_insert({"doctype": ACTION_EXECUTION_DOCTYPE, **values})


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
	provider_event_id: str | None = None,
):
	"""Update only the server-owned execution projection fields."""
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
	if provider_event_id:
		values["provider_event_id"] = provider_event_id
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
	execution_filters = {"attempt": attempt_id} if attempt_id else {"action": action.name}
	execution_name = frappe.db.get_value(ACTION_EXECUTION_DOCTYPE, execution_filters, "name")
	if not execution_name:
		return None
	execution = frappe.get_doc(ACTION_EXECUTION_DOCTYPE, execution_name)
	source_key = f"{execution.name}:{action.get('action_revision') or 0}:{status}:{impact_score}"
	existing = frappe.db.get_value(ACTION_OUTCOME_DOCTYPE, {"source_key": source_key}, "name")
	if existing:
		return frappe.get_doc(ACTION_OUTCOME_DOCTYPE, existing)
	outcome = _service_insert(
		{
			"doctype": ACTION_OUTCOME_DOCTYPE,
			"outcome_id": "NBA-OUT-" + hashlib.sha256(source_key.encode()).hexdigest()[:24],
			"execution": execution.name,
			"recommendation": execution.recommendation,
			"action": action.name,
			"student": action.student,
			"attempt": attempt_id,
			"outcome_type": "action_execution",
			"outcome_value": outcome_code or status,
			"success": 1 if status == "completed" else 0,
			"impact_score": impact_score,
			"captured_by": actor or frappe.session.user,
			"captured_at": now_datetime(),
			"notes": notes,
			"source_key": source_key,
		}
	)
	update_nba_execution(
		execution.attempt,
		status={"completed": "completed", "failed": "failed", "cancelled": "cancelled"}.get(
			status, "in_progress"
		),
		completed_at=outcome.captured_at if status in {"completed", "failed", "cancelled"} else None,
		output={"outcome": outcome_code} if outcome_code else None,
	)
	return outcome


def _sync_nba_recommendation_execution(execution, *, scheduled_at: Any = None):
	"""Keep the Recommendation execution projection monotonic and explicit."""
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
	student: str,
	predicted_probability: float,
	actual_result: str,
	reward: float | None,
	actual_impact: float | None,
	feedback_source: str,
	created_by: str,
	idempotency_key: str | None = None,
):
	"""Create immutable feedback after API-side scope and link validation."""
	if not _doctype_exists(RECOMMENDATION_FEEDBACK_DOCTYPE):
		frappe.throw("CRM Recommendation Feedback is not migrated.", frappe.ValidationError)
	if predicted_probability in (None, ""):
		frappe.throw("predicted_probability is required.", frappe.ValidationError)
	if actual_result in (None, ""):
		frappe.throw("actual_result is required.", frappe.ValidationError)
	predicted_probability = _bounded_number(
		predicted_probability, "predicted_probability", minimum=0.0, maximum=1.0
	)
	reward = _bounded_number(reward, "reward")
	actual_impact = _bounded_number(actual_impact, "actual_impact")
	if feedback_source not in FEEDBACK_SOURCES:
		frappe.throw("Invalid feedback source.", frappe.ValidationError)
	actual_result = str(actual_result)[:500]
	payload = [
		recommendation,
		outcome,
		student,
		predicted_probability,
		actual_result,
		reward,
		actual_impact,
		feedback_source,
		created_by,
	]
	payload_digest = _digest(payload)
	key = idempotency_key or f"nba-feedback:{payload_digest}"
	if len(key) > 180:
		frappe.throw("idempotency_key must not exceed 180 characters.", frappe.ValidationError)
	existing = (
		frappe.db.get_value(
			RECOMMENDATION_FEEDBACK_DOCTYPE,
			{"idempotency_key": key},
			[
				"name",
				"recommendation",
				"outcome",
				"student",
				"predicted_probability",
				"actual_result",
				"reward",
				"actual_impact",
				"feedback_source",
				"created_by",
			],
			as_dict=True,
		)
		if _doctype_exists(RECOMMENDATION_FEEDBACK_DOCTYPE)
		else None
	)
	if existing:
		existing_payload = [
			existing.recommendation,
			existing.outcome,
			existing.student,
			_bounded_number(existing.predicted_probability, "predicted_probability", minimum=0.0, maximum=1.0),
			str(existing.actual_result or "")[:500],
			_bounded_number(existing.reward, "reward"),
			_bounded_number(existing.actual_impact, "actual_impact"),
			existing.feedback_source,
			existing.created_by,
		]
		if _digest(existing_payload) != payload_digest:
			frappe.throw(
				"Idempotency key was already used for another feedback payload.",
				frappe.ValidationError,
				title="IDEMPOTENCY_MISMATCH",
			)
		return frappe.get_doc(RECOMMENDATION_FEEDBACK_DOCTYPE, existing.name)
	return _service_insert(
		{
			"doctype": RECOMMENDATION_FEEDBACK_DOCTYPE,
			"feedback_id": "NBA-FB-" + hashlib.sha256(key.encode()).hexdigest()[:24],
			"recommendation": recommendation,
			"outcome": outcome,
			"student": student,
			"predicted_probability": predicted_probability,
			"actual_result": actual_result,
			"reward": reward,
			"actual_impact": actual_impact,
			"feedback_source": feedback_source,
			"created_by": created_by,
			"created_at": now_datetime(),
			"idempotency_key": key,
		}
	)
