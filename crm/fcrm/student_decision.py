"""Recommendation decisions and canonical Action command service.

This is deliberately the only mutable path for the two aggregates.  It uses
the existing command receipt store as the retry fence; optional Phase 6
contract DocTypes are detected at runtime so an incomplete migrate fails
closed instead of writing a partial audit trail.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.record_retention import technical_retention_until
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.utils.effective import is_effective
from crm.services.action_outcome import allowed_outcomes

RECEIPT = "CRM Student Command Receipt"
DECISION_EVENT = "CRM Student Decision Event"
RECOMMENDATION = "CRM Recommendation"
CANONICAL_ACTION = "CRM Action Item"
POLICY_VERSION = "phase6-v1"
SCHEMA_VERSION = "phase6-v1"
ACTION_TRANSITIONS = {
	"planned": {"in_progress", "cancelled"},
	"accepted": {"in-progress", "cancelled", "deferred"},
	"in_progress": {"completed", "requires-review", "cancelled"},
	"in-progress": {"completed", "requires-review", "cancelled"},
	"completed": set(), "cancelled": set(), "rejected": set(), "superseded": set(),
}
CRM_ACTION_TERMINAL_STATES = frozenset({"completed", "cancelled", "rejected", "superseded"})


# Baseline operational risk for each controlled Action type. An unknown or
# missing type fails closed to "high". "low" means the human performs the
# outreach directly -- the system only opens the dialer and shows the advisory
# script -- so it carries the least automation risk; it is still gated like
# "mid" (no auto-execute) until the low-risk execution guarantees hold
# end to end.
RISK_TIER_POLICY = {
	"CALL": "low",
	"MESSAGE": "mid",
	"EMAIL": "mid",
	"MEETING": "mid",
	"EVENT_INVITE": "mid",
	"CAMPUS_VISIT": "mid",
	"COUNSELING": "mid",
	"DOCUMENT_REQUEST": "mid",
	"APPLICATION_SUPPORT": "high",
	"PARENT_CONTACT": "high",
	"HANDOFF": "high",
}

_RISK_TIER_RANK = {"low": 0, "mid": 1, "high": 2}


def max_risk_tier(*tiers: str | None) -> str:
	"""Highest tier on the ``low < mid < high`` ordering; unknown/None -> ``high``."""
	return max((t for t in tiers), key=lambda t: _RISK_TIER_RANK.get(t or "", 2), default="high") or "high"


def sensitive_content_flags(action_type: str | None, package_seed=None) -> list[str]:
	"""Return the sensitive-content categories that apply to this Action.

	The current policy has no Frappe-owned content signals on CRM Action. Do not
	trust producer-supplied package flags: ``package_seed`` is agent-rendered
	content, even though later edits are protected. A future signal must be
	derived from a Frappe-owned record before it can raise the tier.
	"""
	return ["direct_to_applicant_or_parent"] if action_type == "PARENT_CONTACT" else []


def compute_risk_tier(action_type: str | None, package_seed=None) -> str:
	"""Fail-closed Frappe policy tier; package content cannot affect the result."""
	base = RISK_TIER_POLICY.get(action_type or "", "high")
	if sensitive_content_flags(action_type, package_seed):
		return "high"
	return base


class StudentDecisionError(frappe.ValidationError):
	def __init__(self, code: str, message: str):
		self.code = code
		super().__init__(f"{code}: {message}")


def _fail(code, message):
	raise StudentDecisionError(code, message)


def _meta_fields(doctype):
	try:
		return {f.fieldname for f in frappe.get_meta(doctype).fields}
	except Exception:
		return set()


def _exists(doctype):
	try:
		return bool(frappe.db.table_exists(doctype))
	except Exception:
		return False


def _required(value, label):
	if value in (None, "") or not str(value).strip():
		_fail("INVALID_INPUT", f"{label} is required.")
	return str(value).strip()


def _actor():
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor == "Guest":
		_fail("UNAUTHORIZED", "Authentication is required.")
	return actor


def _scope(actor):
	roles = frappe.get_roles(actor)
	caps = capabilities_for_roles(roles, administrator=actor == "Administrator")
	return {"actor": actor, "roles": sorted(roles), "capabilities": sorted(caps)}


def _can_decide(actor, doc):
	scope = _scope(actor)
	if actor != "Administrator" and not ({"student.execute", "recommendation.decide"} & set(scope["capabilities"])):
		_fail("FORBIDDEN", "You are not permitted to decide recommendations.")
	student_name = doc.get("student")
	if doc.doctype == RECOMMENDATION:
		student_name = doc.target_id if doc.target_type == "CRM Student" else None
	try:
		student = frappe.get_doc("CRM Student", student_name)
	except Exception:
		_fail("OUT_OF_SCOPE", "The recommendation is outside your current scope.")
	if not has_student_permission(student, user=actor, permission_type="read"):
		_fail("OUT_OF_SCOPE", "The recommendation is outside your current scope.")
	return scope


def _staff_for_user(user):
	return frappe.db.get_value("CRM Staff", {"user": user}, "name")


def _active_staff_teams(staff):
	"""Return the currently effective Sales Team memberships for a Staff row."""
	if not staff:
		return set()
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff, "parenttype": "CRM Staff"},
		fields=["team", "effective_from", "effective_until"],
	)
	return {
		row.get("team")
		for row in memberships
		if row.get("team")
		and (
			(not row.get("effective_from") and not row.get("effective_until"))
			or is_effective(row)
		)
	}


def _valid_executor(student, staff, *, allow_global=False):
	"""Keep assignment inside the live Student owner/team scope."""
	staff_row = frappe.db.get_value("CRM Staff", staff, ["user", "is_active"], as_dict=True)
	if not staff_row:
		_fail("INVALID_INPUT", "The selected executor does not exist.")
	if staff_row.get("is_active") in (0, "0", False):
		_fail("INVALID_INPUT", "The selected executor is inactive.")
	user = staff_row.get("user")
	if not user:
		_fail("INVALID_INPUT", "The selected executor is not mapped to a User.")
	user_enabled = frappe.db.get_value("User", user, "enabled")
	if user_enabled in (0, "0", False):
		_fail("INVALID_INPUT", "The selected executor's User is disabled.")
	if not ({"student.execute", "action.execute"} & set(
		capabilities_for_roles(frappe.get_roles(user), administrator=user == "Administrator")
	)):
		_fail("INVALID_INPUT", "The selected executor is not an approved Action executor.")
	if allow_global:
		return
	student_row = frappe.db.get_value(
		"CRM Student", student, ["owner_staff", "assigned_to", "owning_team", "high_school"], as_dict=True
	) or {}
	owner = student_row.get("owner_staff") or student_row.get("assigned_to")
	team = student_row.get("owning_team")
	if staff == owner:
		return
	if team:
		if team in _active_staff_teams(staff):
			return
	# Older Student rows may have a valid owner but no owning_team projection.
	# Derive the fallback from the owner's current team so Lead Sale keeps the
	# same scope that the Student permission query already grants. This does not
	# create a new visibility scope; _can_decide has already checked Student read.
	if not team and owner:
		if _active_staff_teams(owner).intersection(_active_staff_teams(staff)):
			return
	# A school-specific assignment is a valid executor scope even when the
	# Student is still waiting in a different pool projection.  It must still
	# be a current, reviewed assignment; a Zone transfer flags stale rows and
	# therefore cannot silently grant NBA execution access.
	if frappe.db.exists(
		"CRM High School Assignment",
		{"high_school": student_row.get("high_school"), "staff": staff, "status": "Active", "needs_review": 0},
	):
		return
	_fail("OUT_OF_SCOPE", "The executor is outside the Student's current owner/team scope.")


def _fingerprint(payload):
	return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _command_key(kind, actor, key):
	return hashlib.sha256(f"phase6|{kind}|{actor}|{key}".encode()).hexdigest()


def _replay(command_key, fingerprint):
	name = frappe.db.get_value(RECEIPT, {"command_key": command_key}, "name")
	if not name:
		return None
	receipt = frappe.get_doc(RECEIPT, name)
	if receipt.get("request_fingerprint") not in (None, "", fingerprint):
		_fail("IDEMPOTENCY_KEY_REUSED", "The idempotency key was already used for another request.")
	try:
		result = json.loads(receipt.get("result_json") or "")
	except (TypeError, ValueError):
		result = None
	if isinstance(result, dict):
		return {**result, "replayed": True}
	return {"status": receipt.get("outcome") or "applied", "receipt": receipt.name, "replayed": True}


_RECEIPT_KIND_BUCKET = {
	"action_decision": "action_decision",
	"action_reassign": "action_reassign",
	"recommendation_decision": "recommendation_decision",
	# A claim assigns Action ownership; it belongs in the action-decision bucket
	# but keeps its own command_key namespace so a claim retry never collides
	# with a decide/transition/reassign receipt for the same idempotency key.
	"action_claim": "action_decision",
}


def _new_receipt(kind, actor, student, key, fingerprint, scope, correlation_id):
	command_key = _command_key(kind, actor, key)
	return frappe.get_doc({"doctype": RECEIPT, "receipt_key": command_key, "command_key": command_key,
		# The receipt DocType predates CRM Action and has no Action enum yet;
		# reuse its governed student-decision bucket without exposing a legacy
		# writer or creating a second receipt schema.
		"command_kind": _RECEIPT_KIND_BUCKET.get(kind, "interaction_outcome"),
		# `student` is already the canonical CRM Student here (validated by
		# callers). The old `canonical_student` lookup fetched CRM Student.student,
		# which is a back-link to the originating CRM Lead -- wrong doctype for
		# this Link field.
		"request_fingerprint": fingerprint, "outcome": "pending", "target_student": student,
		"target_contact": student,
		"actor": actor, "scope_snapshot": scope, "policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION, "correlation_token": correlation_id, "request_received_at": now_datetime()}).insert(ignore_permissions=True)


def _finish(receipt, result):
	fields = _meta_fields(RECEIPT)
	for field, value in {"outcome": "applied", "result_json": json.dumps(result, default=str), "result_revision": result.get("revision"), "completed_at": now_datetime(), "retention_until": technical_retention_until("receipt")}.items():
		if field in fields:
			receipt.db_set(field, value, update_modified=False)


def _lock(doctype, name):
	frappe.db.sql(f"select name from `tab{doctype}` where name = %s for update", (name,))


def _free_current_slot(student):
	"""Return ``"CURRENT"`` when the student's single Action slot is unoccupied.

	A newly created executor Action -- a manual one, or one materialized from an
	accepted recommendation -- takes the current slot only when no non-terminal
	Action already holds it. The database enforces one current Action per
	student, so callers must run this under a lock on the Student row.
	"""
	occupied = frappe.db.sql(
		"select name from `tabCRM Action Item` where student = %s and current_slot = 'CURRENT' for update",
		(student,),
	)
	return None if occupied else "CURRENT"


def _event(kind, student, recommendation, action, actor, scope, receipt, correlation_id, revision, payload, student_task=None, *, decision_operation=None, action_definition_digest=None, action_definition_revision=None, manual_override=False):
	"""Write audit evidence only when the Phase 6 contract was migrated."""
	if not _exists(DECISION_EVENT):
		_fail("CONTRACT_UNAVAILABLE", "CRM Student Decision Event is not migrated; Phase 6 writes are unavailable.")
	fields = _meta_fields(DECISION_EVENT)
	event_type = "recommendation_decided" if kind.startswith("recommendation.") else {
		"action.accepted": "action_started",
		"action.in_progress": "action_started",
		"action.completed": "action_completed",
		"action.failed": "action_failed",
		"action.cancelled": "action_cancelled",
		"action.rejected": "action_cancelled",
		"action.deferred": "action_superseded",
		"action.reassigned": "action_reassigned",
		"action.manual_override": "action_started",
	}.get(kind, "action_superseded")
	values = {"doctype": DECISION_EVENT, "event_id": frappe.generate_hash(length=20), "student": student,
		"recommendation": recommendation, "action": action, "event_type": event_type, "actor": actor,
		"actor_scope": scope, "command_receipt": receipt.name, "idempotency_key": receipt.command_key,
		"correlation_id": correlation_id or receipt.correlation_token, "aggregate_revision": revision,
		"occurred_at": now_datetime(), "policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION, "delta": payload, "from_state": payload.get("from_state"),
		"to_state": payload.get("status") or kind,
		"reason": payload.get("reason"),
		"decision_operation": decision_operation,
		"action_definition_digest": action_definition_digest,
		"action_definition_revision": action_definition_revision,
		"manual_override": 1 if manual_override else 0}
	return frappe.get_doc({key: value for key, value in values.items() if key == "doctype" or key in fields}).insert(ignore_permissions=True)


def _outbox(event_type, doc):
	if frappe.conf.get("crm_agents_outbox_enabled", 1) in (0, "0", False):
		_fail("OUTBOX_DISABLED", "Phase 6 writes are disabled because the agent outbox is disabled.")
	from crm.api.agent_events import record_agent_event
	return record_agent_event(event_type, doc)


# A parameter delta may adjust only these execution details on acceptance. The
# Action identity (which controlled Action, on which target) is never negotiable
# through a decision -- a different Action is a different recommendation.
_DECISION_DELTA_ALLOWLIST = frozenset({"due_at", "revisit_at", "assignee_staff", "channel", "priority"})
_DECISION_IDENTITY_KEYS = frozenset({"action", "action_type", "action_code", "nba_action", "target_id", "target_type", "student"})
_DECISION_TERMINAL = frozenset({"accepted", "rejected", "dismissed", "dismissed_by_selection"})
_OPERATION_STATUS = {
	"ACCEPT": "accepted",
	"ACCEPT_WITH_CHANGES": "accepted",
	"REJECT": "rejected",
	"DEFER": "deferred",
	"DISMISS": "dismissed",
}


def _normalize_decision_delta(operation: str, delta: Any) -> dict:
	"""Validate an acceptance delta: allowlisted keys only, no identity change."""
	if delta in (None, "", {}):
		if operation == "ACCEPT_WITH_CHANGES":
			_fail("INVALID_INPUT", "ACCEPT_WITH_CHANGES requires a non-empty parameter delta.")
		return {}
	if isinstance(delta, str):
		try:
			delta = json.loads(delta)
		except (TypeError, ValueError):
			_fail("INVALID_INPUT", "The parameter delta is not valid JSON.")
	if not isinstance(delta, dict):
		_fail("INVALID_INPUT", "The parameter delta must be an object.")
	identity = sorted(k for k in delta if k in _DECISION_IDENTITY_KEYS)
	if identity:
		_fail("IDENTITY_CHANGE", f"A decision cannot change the Action identity: {', '.join(identity)}.")
	unknown = sorted(k for k in delta if k not in _DECISION_DELTA_ALLOWLIST)
	if unknown:
		_fail("INVALID_INPUT", f"Unsupported parameter delta keys: {', '.join(unknown)}.")
	if operation != "ACCEPT_WITH_CHANGES":
		_fail("INVALID_INPUT", "A parameter delta is only valid with ACCEPT_WITH_CHANGES.")
	return {k: v for k, v in delta.items() if v not in (None, "")}


def _supersede_evaluation_siblings(doc, *, actor, scope, receipt, correlation_id) -> None:
	"""Dismiss every other still-pending recommendation from the same NBA
	Evaluation once one of them is accepted -- a sale works exactly one of
	the Top-N proposals at a time, never several in parallel.

	A sibling is one produced by the same NBA Evaluation (``doc.evaluation``).
	A legacy row with no ``evaluation`` link (produced outside the epoch
	pipeline) has no siblings to supersede.
	"""
	if not doc.evaluation:
		return
	siblings = frappe.get_all(
		RECOMMENDATION,
		filters={"evaluation": doc.evaluation, "decision_status": "pending", "name": ["!=", doc.name]},
		pluck="name",
	)
	for sibling_name in siblings:
		frappe.db.set_value(
			RECOMMENDATION,
			sibling_name,
			{
				"decision_status": "dismissed_by_selection",
				"lifecycle_status": "superseded",
				"decision_operation": "DISMISS",
				"decided_at": now_datetime(),
				"decided_by": actor,
			},
			update_modified=False,
		)
		_event(
			"recommendation.dismissed_by_selection",
			doc.target_id,
			sibling_name,
			None,
			actor,
			scope,
			receipt,
			correlation_id,
			0,
			{"status": "dismissed_by_selection", "from_state": "pending", "reason": f"superseded_by:{doc.name}"},
			decision_operation="DISMISS",
		)


def decide_recommendation(name: str, expected_revision: Any, status: str | None = None, idempotency_key: str | None = None, correlation_id: str | None = None, decision_reason: str | None = None, due_at: Any = None, assignee_staff: str | None = None, revisit_at: Any = None, defer_kind: str | None = None, expected_modified: str | None = None, operation: str | None = None, delta: Any = None):
	"""Append one Sales Decision for a Recommendation and, only for an accepting
	operation, create exactly one NBA Task in the same transaction.

	``operation`` is the append-only vocabulary (ACCEPT, ACCEPT_WITH_CHANGES,
	REJECT, DEFER, DISMISS); ``status`` stays accepted for the pre-vocabulary
	callers. REJECT / DEFER / DISMISS and passive expiry never create a Task.
	"""
	actor = _actor()
	key = _required(idempotency_key, "idempotency_key")
	correlation_id = correlation_id or frappe.generate_hash(length=20)
	if operation:
		operation = str(operation).strip().upper()
		if operation not in _OPERATION_STATUS:
			_fail("INVALID_INPUT", "Unsupported recommendation decision operation.")
		status = _OPERATION_STATUS[operation]
	else:
		if status not in {"accepted", "rejected", "deferred"}:
			_fail("INVALID_INPUT", "Unsupported recommendation decision.")
		operation = {"accepted": "ACCEPT", "rejected": "REJECT", "deferred": "DEFER"}[status]
	accepting = operation in {"ACCEPT", "ACCEPT_WITH_CHANGES"}
	applied_delta = _normalize_decision_delta(operation, delta)
	if "due_at" in applied_delta:
		due_at = applied_delta["due_at"]
	if "revisit_at" in applied_delta:
		revisit_at = applied_delta["revisit_at"]
	if "assignee_staff" in applied_delta:
		assignee_staff = applied_delta["assignee_staff"]
	payload = {
		"name": name,
		"expected_revision": expected_revision,
		"operation": operation,
		"status": status,
		"decision_reason": decision_reason,
		"due_at": due_at,
		"assignee_staff": assignee_staff,
		"revisit_at": revisit_at,
		"defer_kind": defer_kind,
		"delta": applied_delta,
	}
	fingerprint = _fingerprint(payload)
	command_key = _command_key("recommendation_decision", actor, key)
	if replay := _replay(command_key, fingerprint):
		return replay
	_lock(RECOMMENDATION, name)
	doc = frappe.get_doc(RECOMMENDATION, name)
	scope = _can_decide(actor, doc)
	student_name = doc.target_id if doc.target_type == "CRM Student" else None
	if not student_name:
		_fail("INVALID_INPUT", "Only CRM Student recommendations can be decided.")
	_lock("CRM Student", student_name)
	expires_at = frappe.utils.get_datetime(doc.expires_at) if doc.expires_at else None
	if expires_at and expires_at <= now_datetime():
		_fail("ACTION_EXPIRED", "This recommendation has expired and must be regenerated.")
	# `expected_modified` is the explicit CAS parameter; when a caller does not
	# send it (the frontend sends only `expected_revision`, which the DTO fills
	# with `str(row.modified)`), fall back to comparing `expected_revision`
	# against the live `doc.modified` so the guard is not silently inert.
	cas_expected = expected_modified or expected_revision
	if cas_expected and str(doc.modified) != str(cas_expected):
		_fail("STALE_REVISION", "Recommendation changed; reload before retrying.")
	if doc.decision_status in _DECISION_TERMINAL:
		_fail("INVALID_STATE", "This recommendation can no longer be decided.")
	canonical_type = None
	definition_digest = None
	if accepting:
		from crm.fcrm.action_type_catalog import (
			action_category,
			canonicalize_action_type,
			display_name_for_wire_action_code,
		)
		from crm.fcrm.action_type_registry import is_available_action_type
		from crm.fcrm.student_contact_conversion import contact_for_student
		from crm.services.sales_action_policy import parent_contact_for_student

		action_type = None
		if doc.action:
			action_type = frappe.db.get_value("CRM Action", doc.action, "code") or frappe.db.get_value(
				"CRM Action Definition", doc.action, "code"
			)
			definition_digest = frappe.db.get_value("CRM Action", doc.action, "definition_digest")
		canonical_type = canonicalize_action_type(action_type)
		canonical_type = canonical_type if is_available_action_type(canonical_type) else None
		if canonical_type:
			from crm.fcrm.nba import get_nba_action_definition, nba_action_allowed_actors
			from crm.services.sales_action_policy import require_parent_contact_authority

			require_parent_contact_authority(canonical_type, student_name)
			allowed_actors = nba_action_allowed_actors(get_nba_action_definition({"action": doc.action}))
			if actor != "Administrator" and allowed_actors and not (set(scope["roles"]) & allowed_actors) and "System Manager" not in scope["roles"]:
				_fail("FORBIDDEN", "Your role is not an approved acceptor for this Action.")
		if not due_at:
			due_at = doc.recommended_at or now_datetime()
		assignee_staff = assignee_staff or doc.owner or _staff_for_user(actor)
		if not assignee_staff:
			_fail("INVALID_INPUT", "A mapped Sales executor is required.")
		if assignee_staff != _staff_for_user(actor) and not ({"team.oversee", "admissions.oversee"} & set(scope["capabilities"])) and actor != "Administrator":
			_fail("FORBIDDEN", "You may only assign yourself.")
		_valid_executor(student_name, assignee_staff, allow_global=actor == "Administrator")
	if operation == "REJECT":
		_required(decision_reason, "decision_reason")
	if operation == "DEFER" and not revisit_at:
		_fail("INVALID_INPUT", "A deferred recommendation needs a revisit time.")
	if operation == "DISMISS":
		_required(decision_reason, "decision_reason")
	previous_status = doc.decision_status
	receipt = _new_receipt("recommendation_decision", actor, student_name, key, fingerprint, scope, correlation_id)
	existing_task = frappe.db.get_value(CANONICAL_ACTION, {"recommendation": doc.name}, "name")
	doc.decision_status = status
	doc.lifecycle_status = "active" if status in {"accepted", "deferred"} else "expired"
	doc.decision_operation = operation
	doc.decided_at = now_datetime()
	doc.decided_by = actor
	if accepting:
		doc.execution_status = "not_started"
	doc.save(ignore_permissions=True)
	if accepting:
		# ``owner`` is a custom Recommendation field (the assigned CRM Staff)
		# that shadows the framework ``owner`` column (the doc's creator).
		# Frappe locks every field literally named ``owner`` as set-only-once
		# globally (``frappe.model.meta.py: standard_set_once_fields``),
		# regardless of this doctype's own field config, so routing the
		# reassignment through ``doc.owner = ...`` + ``doc.save()`` raises
		# ``CannotChangeConstantError``. A direct db write bypasses the
		# controller-level constant check the same way the insert-time write
		# in ``commit_nba_evaluation_result`` already has to.
		frappe.db.set_value(RECOMMENDATION, doc.name, "owner", assignee_staff, update_modified=False)
		doc.owner = assignee_staff

	action = existing_task
	if accepting and not existing_task:
		is_parent_action = bool(canonical_type and action_category(canonical_type) == "PARENT")
		action_contact = (
			parent_contact_for_student(student_name)
			if is_parent_action
			else contact_for_student(student_name)
		)
		# A new Lead is a governed CRM Student before it becomes a CRM Student.
		# Non-parent care actions can therefore be accepted against the Student
		# directly. Parent actions remain fail-closed because they require a
		# verified parent recipient and authority.
		if is_parent_action and not action_contact:
			_fail("FORBIDDEN", "A unique governed parent recipient is required for this Action.")
		task_title = (
			display_name_for_wire_action_code(canonical_type or action_type)
			or doc.purpose
			or doc.reason
		)
		canonical = frappe.get_doc(
			{
				"doctype": CANONICAL_ACTION,
				"recommendation": doc.name,
				"student": student_name,
				"contact": action_contact,
				"current_slot": _free_current_slot(student_name),
				"origin": "ai",
				"action": canonical_type,
				"action_type": action_category(canonical_type) if canonical_type else None,
				"action_definition_digest": definition_digest,
				"objective": task_title,
				"description": doc.reason,
				"disposition": "ACT" if canonical_type else "MONITOR",
				"state": "accepted",
				"priority": applied_delta.get("priority") or doc.priority or "medium",
				"source_context_revision": 0,
				"policy_context_version": "nba-v1",
				"generation_idempotency_key": key,
				"producer_identity": "frappe:recommendation",
				"payload_digest": fingerprint,
				"due_at": due_at,
				"action_owner": assignee_staff,
				"accepted_at": now_datetime(),
				"created_at": now_datetime(),
				"action_revision": 1,
				"decision_revision": 1,
			}
		)
		canonical.flags.crm_action_command = True
		canonical.insert(ignore_permissions=True)
		action = canonical.name

	event = _event(
		f"recommendation.{status}",
		student_name,
		doc.name,
		action,
		actor,
		scope,
		receipt,
		correlation_id,
		0,
		{
			"status": status,
			"from_state": previous_status,
			"reason": decision_reason,
			"revisit_at": str(revisit_at) if revisit_at else None,
			"delta": {k: str(v) for k, v in applied_delta.items()} or None,
		},
		decision_operation=operation,
		action_definition_digest=definition_digest,
	)
	projection = {"source_decision_event": event.name}
	if action:
		projection["linked_task"] = action
		previous_flag = getattr(frappe.flags, "crm_action_command", False)
		frappe.flags.crm_action_command = True
		try:
			frappe.db.set_value(CANONICAL_ACTION, action, "source_decision_event", event.name, update_modified=False)
		finally:
			frappe.flags.crm_action_command = previous_flag
	frappe.db.set_value(RECOMMENDATION, doc.name, projection, update_modified=False)
	_outbox("recommendation.decided.v1", event)
	if accepting:
		_supersede_evaluation_siblings(doc, actor=actor, scope=scope, receipt=receipt, correlation_id=correlation_id)
	result = {"status": status, "operation": operation, "recommendation": doc.name, "action": action, "revision": 0, "event": event.name, "receipt": receipt.name}
	_finish(receipt, result)
	return result


def decide_student_task(name: str, expected_revision: Any, status: str, idempotency_key: str, correlation_id: str | None = None, decision_reason: str | None = None, due_at: Any = None, assignee_staff: str | None = None, revisit_at: Any = None, defer_kind: str | None = None, expected_modified: str | None = None):
	"""Canonical Action decision command; function name is API-compatible."""
	actor = _actor(); key = _required(idempotency_key, "idempotency_key"); correlation_id = correlation_id or frappe.generate_hash(length=20)
	if status not in {"accepted", "rejected", "deferred"}: _fail("INVALID_INPUT", "Unsupported task decision.")
	payload = {"name": name, "expected_revision": expected_revision, "status": status, "decision_reason": decision_reason, "due_at": due_at, "assignee_staff": assignee_staff, "revisit_at": revisit_at, "defer_kind": defer_kind}
	fingerprint = _fingerprint(payload); command_key = _command_key("action_decision", actor, key)
	TASK = CANONICAL_ACTION
	if replay := _replay(command_key, fingerprint): return replay
	_lock(TASK, name)
	if replay := _replay(command_key, fingerprint): return replay
	doc = frappe.get_doc(TASK, name); scope = _can_decide(actor, doc)
	if expected_modified and str(doc.modified) != str(expected_modified): _fail("STALE_REVISION", "Action changed; reload before retrying.")
	if str(doc.get("decision_revision") or 0) != str(expected_revision): _fail("STALE_REVISION", "Action changed; reload before retrying.")
	if doc.state not in {"pending", "requires-review"}: _fail("INVALID_STATE", "This action can no longer be decided.")
	if status == "accepted":
		if not due_at: _fail("INVALID_INPUT", "due_at is required when accepting.")
		assignee_staff = assignee_staff or _staff_for_user(actor)
		if not assignee_staff: _fail("INVALID_INPUT", "A mapped Sales executor is required.")
		if assignee_staff != _staff_for_user(actor) and not ({"team.oversee", "admissions.oversee"} & set(scope["capabilities"])) and actor != "Administrator": _fail("FORBIDDEN", "You may only assign yourself.")
		_valid_executor(doc.student, assignee_staff, allow_global=actor == "Administrator")
	if status == "rejected":
		_required(decision_reason, "decision_reason")
	if status == "deferred" and not revisit_at:
		_required(decision_reason, "decision_reason")
	previous_state = doc.state
	receipt = _new_receipt("action_decision", actor, doc.student, key, fingerprint, scope, correlation_id)
	previous_flag = getattr(frappe.flags, "phase6_decision_command", False); frappe.flags.phase6_decision_command = True
	previous_action_flag = getattr(frappe.flags, "crm_action_command", False); frappe.flags.crm_action_command = True
	try:
		doc.state = {"accepted": "accepted", "rejected": "rejected", "deferred": "deferred"}[status]
		doc.decision_reason = decision_reason; doc.revisit_at = revisit_at if status == "deferred" else None
		if status == "accepted":
			doc.due_at = due_at; doc.action_owner = assignee_staff; doc.accepted_at = now_datetime()
		doc.decision_revision = int(doc.get("decision_revision") or 0) + 1; doc.decision_actor = actor; doc.decision_at = now_datetime()
		doc.save(ignore_permissions=True)
		from crm.fcrm.nba import sync_nba_recommendation_for_action
		sync_nba_recommendation_for_action(doc)
		action = doc.name if status == "accepted" else None
		# V2-native decisions are audited only via CRM Student Decision Event.
		# They must never be delivered through the legacy recommendation-decision
		# outbox route: that would keep a V1 delivery path alive under a V2 event
		# name and risk retry/dead-letter traffic against the retired endpoint.
		event = _event(f"action.{status}", doc.student, None, action, actor, scope, receipt, correlation_id, doc.decision_revision, {"status": status, "from_state": previous_state, "reason": decision_reason, "revisit_at": str(revisit_at) if revisit_at else None})
		result = {"status": status, "action": action, "revision": doc.decision_revision, "event": event.name, "receipt": receipt.name}; _finish(receipt, result); return result
	finally:
		frappe.flags.phase6_decision_command = previous_flag
		frappe.flags.crm_action_command = previous_action_flag


_CLAIMABLE_STATES = {"pending", "requires-review", "accepted", "deferred"}


def _claim_would_grant_execute(student: str, staff: str | None, owner_staff, assigned_to) -> bool:
	"""True when a claim actually gives the caller execute rights on the Student.

	Either the Student is unassigned (the claim widens ``assigned_to`` to the
	caller), or the caller already passes ``_valid_executor`` (owner, or on the
	owning team). A claim on a Student already assigned to someone else, by a
	caller outside the owning team, would leave ``assigned_to`` untouched and the
	caller still unable to execute -- so it is not offered and not permitted.
	"""
	if not owner_staff and not assigned_to:
		return True
	if not staff:
		return False
	try:
		_valid_executor(student, staff)
		return True
	except StudentDecisionError:
		return False


def claim_grants_execute(student: str, user: str) -> bool:
	"""``can_claim`` for the care-queue read-model: capability + row visibility +
	the real ``_valid_executor`` rule (see ``_claim_would_grant_execute``)."""
	if user == "Administrator":
		return True
	if not ({"student.execute", "action.execute"} & set(_scope(user)["capabilities"])):
		return False
	staff = _staff_for_user(user)
	if not staff:
		return False
	row = frappe.db.get_value(
		"CRM Student", student, ["owner_staff", "assigned_to"], as_dict=True
	)
	if not row:
		return False
	if not has_student_permission(frappe.get_doc("CRM Student", student), user=user, permission_type="read"):
		return False
	return _claim_would_grant_execute(student, staff, row.owner_staff, row.assigned_to)


def _current_action_payload(student: str) -> dict | None:
	name = frappe.db.get_value(CANONICAL_ACTION, {"student": student, "current_slot": "CURRENT"}, "name")
	if not name:
		return None
	doc = frappe.get_doc(CANONICAL_ACTION, name)
	return {
		"name": doc.name, "action": doc.name, "student": doc.student, "state": doc.state,
		"action_type": doc.action_type, "action_owner": doc.get("action_owner"),
		"risk_tier": doc.get("risk_tier"), "revision": int(doc.get("decision_revision") or 0),
		"action_revision": int(doc.get("action_revision") or 1),
	}


def claim_current_action(student: str, expected_revision: Any, idempotency_key: str, expected_action: str, correlation_id: str | None = None):
	"""Claim the Student's current queue Action for the caller.

	``expected_action`` is required: the caller must send the Action name it saw
	in the queue row. The command locks the CRM Student row -- the same domain
	generation and supersede race on, not the Action row -- and re-verifies that
	the current slot still holds that exact Action. A slot that rotated under the
	caller (superseded, completed, regenerated -- a replacement can even carry the
	same ``decision_revision``) returns ``STALE_REVISION`` with the fresh
	``current_action`` so the client re-renders. Concurrent claims of the same
	Action resolve to exactly one success; the loser gets ``STALE_REVISION`` (CAS
	on ``decision_revision``) or ``ALREADY_CLAIMED`` if the winner got there first.

	Takeover is not allowed: an Action already owned by another Sale returns
	``ALREADY_CLAIMED``. The claim widens the Student's care scope to the caller
	only when the Student is entirely unassigned (``assigned_to`` set, an existing
	assignee never displaced); ``owner_staff`` / ``owning_team`` stay untouched
	and ``_valid_executor`` is unchanged. A caller who would not gain execute
	rights from the claim -- outside the owning team on an already-assigned
	Student -- is rejected, never added.
	"""
	actor = _actor()
	key = _required(idempotency_key, "idempotency_key")
	student = _required(student, "student")
	expected_action = _required(expected_action, "expected_action")
	correlation_id = correlation_id or frappe.generate_hash(length=20)
	if not frappe.db.exists("CRM Student", student):
		_fail("INVALID_INPUT", "Student not found.")
	scope = _scope(actor)
	if actor != "Administrator" and not ({"student.execute", "action.execute"} & set(scope["capabilities"])):
		_fail("FORBIDDEN", "You are not permitted to claim Actions.")
	staff = _staff_for_user(actor)
	if not staff and actor != "Administrator":
		_fail("INVALID_INPUT", "A mapped Sales executor is required to claim work.")
	if actor != "Administrator" and not has_student_permission(
		frappe.get_doc("CRM Student", student), user=actor, permission_type="read"
	):
		_fail("OUT_OF_SCOPE", "The Student is outside your current care scope.")

	payload = {"student": student, "expected_revision": expected_revision, "expected_action": expected_action, "staff": staff}
	fingerprint = _fingerprint(payload)
	command_key = _command_key("action_claim", actor, key)
	if replay := _replay(command_key, fingerprint):
		return replay
	_lock("CRM Student", student)
	if replay := _replay(command_key, fingerprint):
		return replay

	current = frappe.db.sql(
		"select name from `tabCRM Action Item` where student = %s and current_slot = 'CURRENT' for update",
		(student,), as_dict=True,
	)
	stale = {
		"status": "stale_revision", "code": "STALE_REVISION",
		"current_action": _current_action_payload(student),
	}
	if not current or current[0].name != expected_action:
		# No current Action, or the slot rotated to a different Action.
		return stale
	action = frappe.get_doc(CANONICAL_ACTION, current[0].name)
	if str(action.get("decision_revision") or 0) != str(expected_revision):
		return stale
	if action.state not in _CLAIMABLE_STATES:
		return stale

	current_owner = action.get("action_owner")
	if current_owner and current_owner != staff:
		# Takeover is not allowed.
		return {
			"status": "already_claimed", "code": "ALREADY_CLAIMED",
			"assignee_ref": current_owner, "current_action": _current_action_payload(student),
		}

	owner_staff, assigned_to = frappe.db.get_value(
		"CRM Student", student, ["owner_staff", "assigned_to"]
	) or (None, None)
	if not _claim_would_grant_execute(student, staff, owner_staff, assigned_to):
		_fail("OUT_OF_SCOPE", "Claiming would not grant execute rights on this Student.")

	receipt = _new_receipt("action_claim", actor, student, key, fingerprint, scope, correlation_id)
	previous_owner = current_owner
	previous_flag = getattr(frappe.flags, "crm_action_command", False)
	frappe.flags.crm_action_command = True
	try:
		if staff and not owner_staff and not assigned_to:
			frappe.db.set_value("CRM Student", student, "assigned_to", staff, update_modified=False)
		action.action_owner = staff or previous_owner
		action.decision_revision = int(action.get("decision_revision") or 0) + 1
		# Bump the execution revision too: a client holding a pre-claim revision
		# must refetch before it can transition the Action.
		action.action_revision = int(action.get("action_revision") or 1) + 1
		action.decision_actor = actor
		action.decision_at = now_datetime()
		action.save(ignore_permissions=True)
		from crm.fcrm.nba import sync_nba_recommendation_for_action
		sync_nba_recommendation_for_action(action)
		event = _event(
			"action.reassigned", student, action.get("recommendation"), action.name, actor, scope,
			receipt, correlation_id, action.decision_revision,
			{"status": action.state, "previous_assignee": previous_owner, "assignee_staff": staff, "reason": "claimed"},
		)
	finally:
		frappe.flags.crm_action_command = previous_flag
	result = {
		"status": "claimed", "action": action.name, "student": student,
		"revision": action.decision_revision, "action_revision": action.action_revision,
		"previous_owner": previous_owner, "event": event.name, "receipt": receipt.name,
		"current_action": _current_action_payload(student),
	}
	_finish(receipt, result)
	return result


def _record_manual_override(student, action, action_type, actor, scope, receipt, correlation_id):
	"""Log a manual Task that diverges from a still-open AI recommendation.

	This is override telemetry, not a decision: no ``decision_operation`` is set
	and the open recommendation is left ``pending`` so its own passive expiry or a
	later explicit decision still applies. It never fabricates accepted AI advice.
	"""
	from crm.fcrm.action_type_catalog import canonicalize_action_type

	pending = frappe.get_all(
		RECOMMENDATION,
		filters={"target_type": "CRM Student", "target_id": student, "decision_status": "pending"},
		fields=["name", "action"],
		limit_page_length=5,
	)
	for row in pending:
		open_type = canonicalize_action_type(
			frappe.db.get_value("CRM Action", row.action, "code") if row.action else None
		)
		if open_type == action_type:
			continue
		_event(
			"action.manual_override", student, row.name, action.name, actor, scope, receipt,
			correlation_id, 0,
			{"status": "manual_override", "manual_action_type": action_type, "open_recommendation_action": open_type},
			decision_operation=None, manual_override=True,
		)


def create_manual_action(
	student: str,
	action_type: str,
	objective: str,
	idempotency_key: str,
	due_at: Any = None,
	priority: str = "medium",
	assignee_staff: str | None = None,
	contact: str | None = None,
	description: str | None = None,
	start_date: Any = None,
	linked_interaction: str | None = None,
	initial_state: str = "accepted",
):
	"""Create a user-authored Action through the governed aggregate."""
	actor = _actor()
	key = _required(idempotency_key, "idempotency_key")
	objective = _required(objective, "objective")[:500]
	from crm.fcrm.action_type_catalog import action_category, canonicalize_action_type
	from crm.fcrm.action_type_registry import is_available_action_type
	from crm.fcrm.student_contact_conversion import contact_for_student, contact_is_linked_to_student
	from crm.services.sales_action_policy import parent_contact_for_student, require_parent_contact_authority

	action_type = canonicalize_action_type(action_type)
	if not is_available_action_type(action_type):
		_fail("INVALID_INPUT", "Unsupported Action type.")
	if initial_state not in {"pending", "accepted", "in-progress", "completed", "cancelled"}:
		_fail("INVALID_INPUT", "Unsupported initial Action state.")
	try:
		require_parent_contact_authority(action_type, student)
	except frappe.PermissionError as exc:
		_fail("FORBIDDEN", str(exc))
	if priority not in {"high", "medium", "low"}:
		_fail("INVALID_INPUT", "Unsupported Action priority.")
	if contact:
		if not contact_is_linked_to_student(contact, student):
			_fail("INVALID_INPUT", "Contact is not linked to the selected Student.")
	elif action_category(action_type) == "PARENT":
		contact = parent_contact_for_student(student)
		if not contact:
			_fail("FORBIDDEN", "A unique governed parent recipient is required for this Action.")
	else:
		contact = contact_for_student(student)
	student_doc = frappe.get_doc("CRM Student", student)
	scope = _scope(actor)
	if actor != "Administrator" and not has_student_permission(student_doc, user=actor, permission_type="read"):
		_fail("OUT_OF_SCOPE", "The Action is outside your current scope.")
	assignee_staff = assignee_staff or _staff_for_user(actor)
	if not assignee_staff and actor != "Administrator":
		_fail("INVALID_INPUT", "A mapped Sales executor is required.")
	if assignee_staff:
		_valid_executor(student, assignee_staff, allow_global=actor == "Administrator")
	payload = {
		"student": student,
		"contact": contact,
		"action_type": action_type,
		"objective": objective,
		"description": description,
		"start_date": start_date,
		"linked_interaction": linked_interaction,
		"due_at": due_at,
		"priority": priority,
		"assignee_staff": assignee_staff,
		"initial_state": initial_state,
	}
	fingerprint = _fingerprint(payload)
	command_key = _command_key("manual_action", actor, key)
	if replay := _replay(command_key, fingerprint):
		return replay
	_lock("CRM Student", student)
	receipt = _new_receipt("action_decision", actor, student, key, fingerprint, scope, frappe.generate_hash(length=20))
	previous_flag = getattr(frappe.flags, "crm_action_command", False)
	frappe.flags.crm_action_command = True
	try:
		now = now_datetime()
		action = frappe.get_doc(
			{
				"doctype": CANONICAL_ACTION,
				"student": student,
				"contact": contact,
				"current_slot": _free_current_slot(student),
				"origin": "manual",
				"action": action_type,
				"action_type": action_category(action_type),
				"objective": objective,
				"description": description,
				"start_date": start_date,
				"linked_interaction": linked_interaction,
				"disposition": "ACT",
				"state": initial_state,
				"execution_status": "completed" if initial_state == "completed" else "in_progress" if initial_state == "in-progress" else "cancelled" if initial_state == "cancelled" else "planned",
				"priority": priority,
				"due_at": due_at,
				"action_owner": assignee_staff,
				"source_context_revision": int(student_doc.get("student_context_revision") or 0),
				"policy_context_version": POLICY_VERSION,
				"generation_idempotency_key": command_key,
				"producer_identity": f"user:{actor}",
				"payload_digest": fingerprint,
				"accepted_at": now if initial_state != "pending" else None,
				"completed_at": now if initial_state == "completed" else None,
				"created_at": now,
				"started_at": now if initial_state == "in-progress" else None,
				"action_revision": 1,
				"decision_revision": 1,
			}
		).insert(ignore_permissions=True)
		_record_manual_override(student, action, action_type, actor, scope, receipt, command_key)
		result = {
			"status": "accepted" if initial_state == "accepted" else initial_state,
			"action": action.name,
			"student": student,
			"revision": action.action_revision,
			"receipt": receipt.name,
		}
		_finish(receipt, result)
		return result
	finally:
		frappe.flags.crm_action_command = previous_flag


def update_manual_action(
	name: str,
	*,
	title: str | None = None,
	description: str | None = None,
	start_date: Any = None,
	priority: str | None = None,
	due_at: Any = None,
	assignee_staff: str | None = None,
	action_state: str | None = None,
	linked_interaction: str | None = None,
	idempotency_key: str,
	correlation_id: str | None = None,
):
	"""Update a manually-created Action through the Task compatibility facade.

	The legacy Task API has no expected revision or outcome payload.  The
	compatibility command therefore keeps the aggregate lock and audit receipt,
	while allowing the old CRUD status vocabulary to move an Action directly.
	Canonical lifecycle endpoints remain stricter and still require outcome
	evidence when completing an Action.
	"""
	actor = _actor()
	key = _required(idempotency_key, "idempotency_key")
	correlation_id = correlation_id or frappe.generate_hash(length=20)
	if action_state and action_state not in {
		"pending", "accepted", "in-progress", "requires-review", "deferred",
		"completed", "cancelled", "rejected", "superseded",
	}:
		_fail("INVALID_INPUT", "Unsupported Action state.")
	if priority is not None and priority not in {"high", "medium", "low"}:
		_fail("INVALID_INPUT", "Unsupported Action priority.")
	if title is not None:
		title = _required(title, "title")[:500]

	payload = {
		"name": name,
		"title": title,
		"description": description,
		"start_date": start_date,
		"priority": priority,
		"due_at": due_at,
		"assignee_staff": assignee_staff,
		"action_state": action_state,
		"linked_interaction": linked_interaction,
	}
	fingerprint = _fingerprint(payload)
	command_key = _command_key("manual_action_update", actor, key)
	if replay := _replay(command_key, fingerprint):
		return replay

	_lock(CANONICAL_ACTION, name)
	action = frappe.get_doc(CANONICAL_ACTION, name)
	scope = _can_decide(actor, action)
	if action.get("legacy_task_deleted"):
		_fail("INVALID_STATE", "This Task has been deleted.")
	if assignee_staff:
		own_staff = _staff_for_user(actor)
		if actor != "Administrator" and assignee_staff != own_staff and not (
			{"team.oversee", "admissions.oversee"} & set(scope["capabilities"])
		):
			_fail("FORBIDDEN", "You may only assign yourself.")
		_valid_executor(action.student, assignee_staff, allow_global=actor == "Administrator")

	receipt = _new_receipt(
		"action_decision", actor, action.student, key, fingerprint, scope, correlation_id
	)
	previous_state = action.state
	previous_flag = getattr(frappe.flags, "crm_action_command", False)
	previous_compatibility_flag = getattr(frappe.flags, "crm_action_compatibility_command", False)
	frappe.flags.crm_action_command = True
	frappe.flags.crm_action_compatibility_command = True
	try:
		if title is not None:
			action.objective = title
		if description is not None:
			action.description = description
		if start_date is not None:
			action.start_date = start_date
		if priority is not None:
			action.priority = priority
		if due_at is not None:
			action.due_at = due_at
		if assignee_staff is not None:
			action.action_owner = assignee_staff
		if linked_interaction is not None:
			action.linked_interaction = linked_interaction
		if action_state is not None:
			action.state = action_state
			action.execution_status = {
				"completed": "completed",
				"in-progress": "in_progress",
				"cancelled": "cancelled",
				"rejected": "cancelled",
				"superseded": "cancelled",
			}.get(action.state, "planned")
		if action.state == "in-progress" and not action.started_at:
			action.started_at = now_datetime()
		if action.state == "completed":
			action.completed_at = now_datetime()
		if action.state in {"cancelled", "rejected", "superseded"}:
			action.terminal_reason = "Updated through the Task API compatibility facade."
		action.action_revision = int(action.get("action_revision") or 1) + 1
		action.decision_actor = actor
		action.decision_at = now_datetime()
		action.save(ignore_permissions=True)
		event = _event(
			"action.manual_override", action.student, action.get("recommendation"), action.name,
			actor, scope, receipt, correlation_id, action.action_revision,
			{
				"status": action.state,
				"from_state": previous_state,
				"reason": "Task API compatibility update",
			},
			manual_override=True,
		)
		result = {
			"status": "updated",
			"action": action.name,
			"student": action.student,
			"revision": action.action_revision,
			"event": event.name,
			"receipt": receipt.name,
		}
		_finish(receipt, result)
		return result
	finally:
		frappe.flags.crm_action_command = previous_flag
		frappe.flags.crm_action_compatibility_command = previous_compatibility_flag


def delete_manual_action(name: str, *, idempotency_key: str, correlation_id: str | None = None):
	"""Soft-delete an Action while preserving its audit trail and name."""
	actor = _actor()
	key = _required(idempotency_key, "idempotency_key")
	correlation_id = correlation_id or frappe.generate_hash(length=20)
	payload = {"name": name, "operation": "DELETE"}
	fingerprint = _fingerprint(payload)
	command_key = _command_key("manual_action_delete", actor, key)
	if replay := _replay(command_key, fingerprint):
		return replay

	_lock(CANONICAL_ACTION, name)
	action = frappe.get_doc(CANONICAL_ACTION, name)
	scope = _can_decide(actor, action)
	if action.get("legacy_task_deleted"):
		return {"status": "deleted", "action": name, "student": action.student, "revision": action.action_revision}
	receipt = _new_receipt(
		"action_decision", actor, action.student, key, fingerprint, scope, correlation_id
	)
	previous_state = action.state
	previous_flag = getattr(frappe.flags, "crm_action_command", False)
	previous_compatibility_flag = getattr(frappe.flags, "crm_action_compatibility_command", False)
	frappe.flags.crm_action_command = True
	frappe.flags.crm_action_compatibility_command = True
	try:
		if action.state not in CRM_ACTION_TERMINAL_STATES:
			action.state = "cancelled"
			action.execution_status = "cancelled"
			action.terminal_reason = "Deleted through the Task API compatibility facade."
		action.legacy_task_deleted = 1
		action.action_revision = int(action.get("action_revision") or 1) + 1
		action.decision_actor = actor
		action.decision_at = now_datetime()
		action.save(ignore_permissions=True)
		event = _event(
			"action.manual_override", action.student, action.get("recommendation"), action.name,
			actor, scope, receipt, correlation_id, action.action_revision,
			{
				"status": "deleted",
				"from_state": previous_state,
				"reason": "Task API compatibility delete",
			},
			manual_override=True,
		)
		result = {
			"status": "deleted",
			"action": action.name,
			"student": action.student,
			"revision": action.action_revision,
			"event": event.name,
			"receipt": receipt.name,
		}
		_finish(receipt, result)
		return result
	finally:
		frappe.flags.crm_action_command = previous_flag
		frappe.flags.crm_action_compatibility_command = previous_compatibility_flag


def _transition_canonical_action(name: str, expected_revision: Any, status: str, idempotency_key: str, correlation_id: str | None = None, outcome_code: str | None = None, evidence: Any = None, reason: str | None = None, linked_interaction: str | None = None, expected_modified: str | None = None, attempt_id: str | None = None, impact_score: float | None = None):
	"""Transition the single CRM Action aggregate and record its outcome."""
	actor = _actor(); key = _required(idempotency_key, "idempotency_key"); correlation_id = correlation_id or frappe.generate_hash(length=20)
	if status not in {"in_progress", "completed", "failed", "cancelled"}:
		_fail("INVALID_INPUT", "Unsupported Action transition.")
	action = frappe.get_doc(CANONICAL_ACTION, name); scope = _can_decide(actor, action)
	if expected_modified and str(action.modified) != str(expected_modified): _fail("STALE_REVISION", "Action changed; reload before retrying.")
	if str(action.get("action_revision") or 1) != str(expected_revision): _fail("STALE_REVISION", "Action changed; reload before retrying.")
	previous = action.state
	target_state = {"in_progress": "in-progress", "completed": "completed", "failed": "requires-review", "cancelled": "cancelled"}[status]
	if target_state not in ACTION_TRANSITIONS.get(previous, set()): _fail("INVALID_STATE", "Illegal Action transition.")
	if status == "completed":
		action_code = action.get("action") or action.action_type
		if outcome_code not in allowed_outcomes(action_code):
			_fail(
				"INVALID_INPUT",
				f"outcome_code must be one of {sorted(allowed_outcomes(action_code))} for this action.",
			)
		_required(evidence, "evidence")
		if not attempt_id:
			_fail("ATTEMPT_REQUIRED", "A confirmed execution attempt is required before completion.")
		attempt = frappe.db.get_value("CRM Action Execution Attempt", attempt_id, ["action", "status"], as_dict=True)
		if not attempt or attempt.action != name or attempt.status != "confirmed":
			_fail("ATTEMPT_NOT_CONFIRMED", "The execution attempt is not confirmed for this Action.")
	if status in {"failed", "cancelled"}: _required(reason, "reason")
	payload = {"name": name, "expected_revision": expected_revision, "status": status, "outcome_code": outcome_code, "evidence": evidence, "reason": reason, "linked_interaction": linked_interaction, "impact_score": impact_score}
	fingerprint = _fingerprint(payload); command_key = _command_key("canonical_action", actor, key)
	if replay := _replay(command_key, fingerprint): return replay
	_lock(CANONICAL_ACTION, name)
	if replay := _replay(command_key, fingerprint): return replay
	receipt = _new_receipt("action_decision", actor, action.student, key, fingerprint, scope, correlation_id)
	previous_flag = getattr(frappe.flags, "crm_action_command", False); frappe.flags.crm_action_command = True
	try:
		action.state = target_state; action.execution_status = status
		action.action_revision = int(action.get("action_revision") or 1) + 1
		if status == "in_progress": action.started_at = now_datetime()
		if status == "completed":
			action.completed_at = now_datetime(); action.outcome_code = outcome_code; action.outcome_evidence = str(evidence)[:2000]; action.outcome_notes = evidence if isinstance(evidence, str) else None; action.linked_interaction = linked_interaction
			if not action.linked_interaction:
				from crm.fcrm.interaction_log import create_interaction_for_completed_action
				action.linked_interaction = create_interaction_for_completed_action(action)
		if status in {"failed", "cancelled"}: action.terminal_reason = reason
		action.save(ignore_permissions=True)
		from crm.fcrm.nba import record_nba_outcome_for_action, sync_nba_recommendation_for_action
		sync_nba_recommendation_for_action(action)
		nba_outcome = record_nba_outcome_for_action(
			action,
			status=status,
			outcome_code=outcome_code,
			attempt_id=attempt_id,
			notes=reason or (str(evidence)[:2000] if evidence else None),
			actor=actor,
			impact_score=impact_score,
		) if status in {"completed", "failed", "cancelled"} else None
		progress = "UNKNOWN"
		context_revision = None
		if status in {"completed", "failed", "cancelled"}:
			from crm.services.action_outcome import derive_progress
			from crm.services.student_context import bump_student_context_revision
			progress = derive_progress(action.get("action") or action.action_type, outcome_code) if status == "completed" else "NO_PROGRESS"
			attempt_identity = attempt_id or "manual"
			business_event_id = _fingerprint({"action": action.name, "revision": action.action_revision, "attempt": attempt_identity, "outcome": outcome_code, "progress": progress})[:32]
			# This path records a bounded fact only. It deliberately disables the
			# context helper's automatic Intelligence Run admission.
			change = bump_student_context_revision(action.student, "action_outcome", enqueue=False, event_id=business_event_id)
			context_revision = change["revision"]
			from crm.services.admission_event_policy import admit_action_outcome
			admit_action_outcome(student=action.student, revision=context_revision, source_event=change["change"], source_reference=action.name)
		if status == "completed":
			if action.get("recommendation"):
				frappe.db.set_value(
					"CRM Recommendation", action.get("recommendation"), "lifecycle_status", "completed", update_modified=False
				)
			frappe.enqueue(
				"crm.api.agent_events.record_domain_reevaluation_trigger",
				queue="short",
				enqueue_after_commit=True,
				student=action.student,
				trigger="action_outcome_recorded",
			)
		event = _event(f"action.{status}", action.student, action.get("recommendation"), action.name, actor, scope, receipt, correlation_id, action.action_revision, {"status": status, "from_state": previous, "outcome_code": outcome_code, "progress": progress, "context_revision": context_revision, "reason": reason})
		_outbox("action.outcome_recorded.v1", action)
		result = {"status": status, "action": action.name, "student": action.student, "revision": action.action_revision, "event": event.name, "receipt": receipt.name, "nba_outcome": nba_outcome.name if nba_outcome else None}
		_finish(receipt, result); return result
	finally:
		frappe.flags.crm_action_command = previous_flag


def transition_action(name: str, expected_revision: Any, status: str, idempotency_key: str, correlation_id: str | None = None, outcome_code: str | None = None, evidence: Any = None, reason: str | None = None, linked_interaction: str | None = None, expected_modified: str | None = None, attempt_id: str | None = None, _internal_service: bool = False, impact_score: float | None = None):
	if _internal_service:
		previous_user = frappe.session.user
		frappe.session.user = "Administrator"
		try:
			return _transition_canonical_action(name, expected_revision, status, idempotency_key, correlation_id, outcome_code, evidence, reason, linked_interaction, expected_modified, attempt_id, impact_score)
		finally:
			frappe.session.user = previous_user
	return _transition_canonical_action(name, expected_revision, status, idempotency_key, correlation_id, outcome_code, evidence, reason, linked_interaction, expected_modified, attempt_id, impact_score)


def reassign_action(name: str, expected_revision: Any, assignee_staff: str, idempotency_key: str, reason: str, correlation_id: str | None = None, _internal_service: bool = False):
	"""CAS/idempotent reassignment for the canonical Action aggregate."""
	actor = "Administrator" if _internal_service else _actor()
	key = _required(idempotency_key, "idempotency_key")
	reason = _required(reason, "reason")
	correlation_id = correlation_id or frappe.generate_hash(length=20)
	action = frappe.get_doc(CANONICAL_ACTION, name)
	scope = _scope(actor)
	if actor != "Administrator" and not action.has_permission("read"):
		_fail("OUT_OF_SCOPE", "The Action is outside your current scope.")
	if actor != "Administrator" and not ({"student.execute", "action.reassign"} & set(scope["capabilities"])):
		_fail("FORBIDDEN", "You are not permitted to reassign Actions.")
	if str(action.get("action_revision") or 1) != str(expected_revision):
		_fail("STALE_REVISION", "Action changed; reload before retrying.")
	if action.get("execution_status") not in {"planned", "in_progress"}:
		_fail("INVALID_STATE", "Only active Actions may be reassigned.")
	_valid_executor(action.student, assignee_staff, allow_global=actor == "Administrator")
	payload = {"name": name, "expected_revision": expected_revision, "assignee_staff": assignee_staff, "reason": reason}
	fingerprint = _fingerprint(payload); command_key = _command_key("action_reassign", actor, key)
	if replay := _replay(command_key, fingerprint): return replay
	# Claim/reassign and generation share the Student lock domain. Cancel
	# unsent attempts before changing ownership so workers cannot send stale work.
	_lock("CRM Student", action.student)
	_lock(CANONICAL_ACTION, name)
	if replay := _replay(command_key, fingerprint): return replay
	receipt = _new_receipt("action_reassign", actor, action.student, key, fingerprint, scope, correlation_id)
	previous_flag = getattr(frappe.flags, "crm_action_command", False); frappe.flags.crm_action_command = True
	try:
		previous_assignee = action.action_owner
		frappe.db.sql("update `tabCRM Action Execution Attempt` set status='cancelled' where action=%s and status in ('pending','queued')", (action.name,))
		action.action_owner = assignee_staff
		action.action_revision = int(action.get("action_revision") or 1) + 1
		action.save(ignore_permissions=True)
		from crm.fcrm.nba import sync_nba_recommendation_for_action
		sync_nba_recommendation_for_action(action)
		event = _event("action.reassigned", action.student, action.get("recommendation"), action.name, actor, scope, receipt, correlation_id, action.action_revision, {"status": action.get("execution_status") or action.state, "previous_assignee": previous_assignee, "assignee_staff": assignee_staff, "reason": reason})
		result = {"status": "reassigned", "action": action.name, "assignee_staff": assignee_staff, "revision": action.action_revision, "event": event.name, "receipt": receipt.name}
		_finish(receipt, result); return result
	finally:
		frappe.flags.crm_action_command = previous_flag


def release_action(name: str, expected_revision: Any, idempotency_key: str, reason: str, correlation_id: str | None = None):
	"""Release only the active claimant; never reopen or reassign a terminal Action."""
	actor = _actor(); key = _required(idempotency_key, "idempotency_key"); reason = _required(reason, "reason"); correlation_id = correlation_id or frappe.generate_hash(length=20)
	action = frappe.get_doc(CANONICAL_ACTION, name)
	staff = _staff_for_user(actor)
	if not staff or action.get("action_owner") != staff:
		_fail("FORBIDDEN", "Only the active claimant may release this Action.")
	if action.get("execution_status") not in {"planned", "in_progress"}:
		_fail("INVALID_STATE", "Only active Actions may be released.")
	if str(action.get("action_revision") or 1) != str(expected_revision):
		_fail("STALE_REVISION", "Action changed; reload before retrying.")
	payload = {"name": name, "expected_revision": expected_revision, "reason": reason}
	fingerprint = _fingerprint(payload); command_key = _command_key("action_release", actor, key)
	if replay := _replay(command_key, fingerprint): return replay
	_lock("CRM Student", action.student); _lock(CANONICAL_ACTION, name)
	action.reload()
	if str(action.get("action_revision") or 1) != str(expected_revision):
		_fail("STALE_REVISION", "Action changed; reload before retrying.")
	receipt = _new_receipt("action_release", actor, action.student, key, fingerprint, _scope(actor), correlation_id)
	frappe.db.sql("update `tabCRM Action Execution Attempt` set status='cancelled' where action=%s and status in ('pending','queued')", (action.name,))
	action.action_owner = None
	action.action_revision = int(action.get("action_revision") or 1) + 1
	action.save(ignore_permissions=True)
	from crm.fcrm.nba import sync_nba_recommendation_for_action
	sync_nba_recommendation_for_action(action)
	event = _event("action.released", action.student, action.get("recommendation"), action.name, actor, _scope(actor), receipt, correlation_id, action.action_revision, {"reason": reason})
	result = {"status": "released", "action": action.name, "revision": action.action_revision, "event": event.name, "receipt": receipt.name}
	_finish(receipt, result)
	return result


def reconcile_student_actions(student: str, next_owner_staff: str | None, next_owning_team: str | None, correlation_id: str):
	"""Reconcile active work after an authoritative Student ownership change."""
	rows = frappe.get_all(CANONICAL_ACTION, filters={"student": student, "state": ["in", ["accepted", "in-progress"]]}, fields=["name", "action_revision"])
	for row in rows:
		key = f"ownership-reconcile-{correlation_id}-{row.name}"
		if next_owner_staff:
			try:
				reassign_action(row.name, row.action_revision or 1, next_owner_staff, key, "Student ownership changed; action reassigned to current owner.", correlation_id, _internal_service=True)
			except StudentDecisionError:
				transition_action(row.name, row.action_revision or 1, "cancelled", key + "-cancel", correlation_id=correlation_id, reason="Student ownership changed and no executable owner was available.", _internal_service=True)
		else:
			transition_action(row.name, row.action_revision or 1, "cancelled", key + "-cancel", correlation_id=correlation_id, reason="Student ownership moved to an unassigned team pool.", _internal_service=True)
