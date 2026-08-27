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
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.permissions import has_permission as has_student_permission
from crm.fcrm.record_retention import technical_retention_until
from crm.fcrm.role_policy import capabilities_for_roles

RECEIPT = "CRM Student Command Receipt"
DECISION_EVENT = "CRM Student Decision Event"
RECOMMENDATION = "CRM Recommendation"
CANONICAL_ACTION = "CRM Action"
POLICY_VERSION = "phase6-v1"
SCHEMA_VERSION = "phase6-v1"
OUTCOMES = {"NO_RESPONSE", "INTEREST_INCREASED", "NEEDS_MORE_INFORMATION", "CALL_BACK_LATER", "APPLICATION_STARTED", "APPLICATION_COMPLETED", "NOT_INTERESTED"}


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
	try:
		student = frappe.get_doc("CRM Student", doc.student)
	except Exception:
		_fail("OUT_OF_SCOPE", "The recommendation is outside your current scope.")
	if not has_student_permission(student, user=actor, permission_type="read"):
		_fail("OUT_OF_SCOPE", "The recommendation is outside your current scope.")
	return scope


def _staff_for_user(user):
	return frappe.db.get_value("CRM Staff", {"user": user}, "name")


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
		"CRM Student", student, ["owner_staff", "assigned_to", "owning_team"], as_dict=True
	) or {}
	owner = student_row.get("owner_staff") or student_row.get("assigned_to")
	team = student_row.get("owning_team")
	if staff == owner:
		return
	if team and frappe.db.exists(
		"CRM Team Membership", {"parent": staff, "parenttype": "CRM Staff", "team": team}
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


def _new_receipt(kind, actor, student, key, fingerprint, scope, correlation_id):
	command_key = _command_key(kind, actor, key)
	return frappe.get_doc({"doctype": RECEIPT, "receipt_key": command_key, "command_key": command_key,
		# The receipt DocType predates CRM Action and has no Action enum yet;
		# reuse its governed student-decision bucket without exposing a legacy
		# writer or creating a second receipt schema.
		"command_kind": kind if kind in {"action_decision", "action_reassign", "recommendation_decision"} else "interaction_outcome",
		"request_fingerprint": fingerprint, "outcome": "pending", "target_student": student,
		"actor": actor, "scope_snapshot": scope, "policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION, "correlation_token": correlation_id, "request_received_at": now_datetime()}).insert(ignore_permissions=True)


def _finish(receipt, result):
	fields = _meta_fields(RECEIPT)
	for field, value in {"outcome": "applied", "result_json": json.dumps(result, default=str), "result_revision": result.get("revision"), "completed_at": now_datetime(), "retention_until": technical_retention_until("receipt")}.items():
		if field in fields:
			receipt.db_set(field, value, update_modified=False)


def _lock(doctype, name):
	frappe.db.sql(f"select name from `tab{doctype}` where name = %s for update", (name,))


def _event(kind, student, recommendation, action, actor, scope, receipt, correlation_id, revision, payload, student_task=None):
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
	}.get(kind, "action_superseded")
	values = {"doctype": DECISION_EVENT, "event_id": frappe.generate_hash(length=20), "student": student,
		"recommendation": recommendation, "action": action, "event_type": event_type, "actor": actor,
		"actor_scope": scope, "command_receipt": receipt.name, "idempotency_key": receipt.command_key,
		"correlation_id": correlation_id or receipt.correlation_token, "aggregate_revision": revision,
		"occurred_at": now_datetime(), "policy_version": POLICY_VERSION,
		"schema_version": SCHEMA_VERSION, "delta": payload, "from_state": payload.get("from_state"),
		"to_state": payload.get("status") or kind,
		"reason": payload.get("reason")}
	return frappe.get_doc({key: value for key, value in values.items() if key == "doctype" or key in fields}).insert(ignore_permissions=True)


def _outbox(event_type, doc):
	if frappe.conf.get("crm_agents_outbox_enabled", 1) in (0, "0", False):
		_fail("OUTBOX_DISABLED", "Phase 6 writes are disabled because the agent outbox is disabled.")
	from crm.api.agent_events import record_agent_event
	return record_agent_event(event_type, doc)


def decide_recommendation(name: str, expected_revision: Any, status: str, idempotency_key: str, correlation_id: str | None = None, decision_reason: str | None = None, due_at: Any = None, assignee_staff: str | None = None, revisit_at: Any = None, defer_kind: str | None = None, expected_modified: str | None = None):
	actor = _actor(); key = _required(idempotency_key, "idempotency_key"); correlation_id = correlation_id or frappe.generate_hash(length=20)
	if status not in {"accepted", "rejected", "deferred"}: _fail("INVALID_INPUT", "Unsupported recommendation decision.")
	payload = {"name": name, "expected_revision": expected_revision, "status": status, "decision_reason": decision_reason, "due_at": due_at, "assignee_staff": assignee_staff, "revisit_at": revisit_at, "defer_kind": defer_kind}
	fingerprint = _fingerprint(payload); command_key = _command_key("recommendation_decision", actor, key)
	if replay := _replay(command_key, fingerprint): return replay
	_lock(RECOMMENDATION, name)
	if replay := _replay(command_key, fingerprint): return replay
	doc = frappe.get_doc(RECOMMENDATION, name); scope = _can_decide(actor, doc)
	if expected_modified and str(doc.modified) != str(expected_modified): _fail("STALE_REVISION", "Recommendation changed; reload before retrying.")
	if str(doc.get("decision_revision") or 0) != str(expected_revision): _fail("STALE_REVISION", "Recommendation changed; reload before retrying.")
	if doc.status in {"accepted", "rejected", "expired", "superseded", "dismissed", "modified"}: _fail("INVALID_STATE", "This recommendation can no longer be decided.")
	if status == "accepted":
		if not due_at: _fail("INVALID_INPUT", "due_at is required when accepting.")
		assignee_staff = assignee_staff or _staff_for_user(actor)
		if not assignee_staff: _fail("INVALID_INPUT", "A mapped Sales executor is required.")
		if assignee_staff != _staff_for_user(actor) and not ({"team.oversee", "admissions.oversee"} & set(scope["capabilities"])) and actor != "Administrator": _fail("FORBIDDEN", "You may only assign yourself.")
		_valid_executor(
			doc.student,
			assignee_staff,
			allow_global=actor == "Administrator",
		)
	if status == "rejected":
		_required(decision_reason, "decision_reason")
	if status == "deferred" and not revisit_at:
		_required(decision_reason, "decision_reason")
	previous_status = doc.status
	receipt = _new_receipt("recommendation_decision", actor, doc.student, key, fingerprint, scope, correlation_id)
	previous_flag = getattr(frappe.flags, "phase6_decision_command", False); frappe.flags.phase6_decision_command = True
	try:
		doc.flags.from_phase6_command = True
		doc.status = status; doc.decision_reason = decision_reason; doc.revisit_at = revisit_at if status == "deferred" else None
		doc.decision_revision = int(doc.get("decision_revision") or 0) + 1; doc.decision_actor = actor; doc.decision_at = now_datetime(); doc.decision_scope = scope; doc.decision_correlation_id = correlation_id; doc.decision_idempotency_key = key
		doc.save(ignore_permissions=True)
		action = None
		if status == "accepted":
			action = frappe.db.get_value(CANONICAL_ACTION, {"recommendation": doc.name}, "name")
			if not action:
				canonical_type = doc.recommended_action if doc.recommended_action in {"CALL", "EMAIL", "MESSAGE", "COUNSELING", "MEETING", "EVENT_INVITE", "CAMPUS_VISIT", "DOCUMENT_REQUEST", "APPLICATION_SUPPORT", "PARENT_CONTACT", "HANDOFF"} else None
				canonical = frappe.get_doc({"doctype": CANONICAL_ACTION, "recommendation": doc.name, "student": doc.student, "contact": frappe.db.get_value("CRM Contact", {"student": doc.student}, "name"), "origin": "ai" if doc.get("producer_id") else "system", "action_type": canonical_type, "objective": doc.get("rationale") or doc.get("recommended_action") or "Follow up on the recommendation.", "disposition": "ACT" if canonical_type else "MONITOR", "state": "accepted", "source_context_revision": 0, "policy_context_version": POLICY_VERSION, "generation_idempotency_key": key, "producer_identity": "frappe:recommendation", "payload_digest": _fingerprint(payload), "due_at": due_at, "action_owner": assignee_staff, "accepted_at": now_datetime(), "created_at": now_datetime(), "action_revision": 1, "decision_revision": 1})
				canonical.origin = "ai" if doc.get("producer_id") else "system"
				canonical.flags.crm_action_command = True; canonical.insert(ignore_permissions=True); action = canonical.name
		event = _event(f"recommendation.{status}", doc.student, doc.name, action, actor, scope, receipt, correlation_id, doc.decision_revision, {"status": status, "from_state": previous_status, "reason": decision_reason, "revisit_at": str(revisit_at) if revisit_at else None})
		_outbox("recommendation.decided.v1", event)
		result = {"status": status, "recommendation": doc.name, "action": action, "revision": doc.decision_revision, "event": event.name, "receipt": receipt.name}; _finish(receipt, result); return result
	finally:
		frappe.flags.phase6_decision_command = previous_flag


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


def create_manual_action(student: str, action_type: str, objective: str, idempotency_key: str, due_at: Any = None, priority: str = "medium", assignee_staff: str | None = None, contact: str | None = None):
	"""Create a user-authored Action through the governed aggregate."""
	actor = _actor(); key = _required(idempotency_key, "idempotency_key"); objective = _required(objective, "objective")[:500]
	if action_type not in {"CALL", "EMAIL", "MESSAGE", "COUNSELING", "MEETING", "EVENT_INVITE", "CAMPUS_VISIT", "DOCUMENT_REQUEST", "APPLICATION_SUPPORT", "PARENT_CONTACT", "HANDOFF"}:
		_fail("INVALID_INPUT", "Unsupported Action type.")
	if priority not in {"high", "medium", "low"}: _fail("INVALID_INPUT", "Unsupported Action priority.")
	if contact:
		linked_student = frappe.db.get_value("CRM Contact", contact, "student")
		if not linked_student or linked_student != student:
			_fail("INVALID_INPUT", "Contact is not linked to the selected Student.")
	student_doc = frappe.get_doc("CRM Student", student); scope = _scope(actor)
	if actor != "Administrator" and not has_student_permission(student_doc, user=actor, permission_type="read"):
		_fail("OUT_OF_SCOPE", "The Action is outside your current scope.")
	assignee_staff = assignee_staff or _staff_for_user(actor)
	if not assignee_staff: _fail("INVALID_INPUT", "A mapped Sales executor is required.")
	_valid_executor(student, assignee_staff, allow_global=actor == "Administrator")
	payload = {"student": student, "contact": contact, "action_type": action_type, "objective": objective, "due_at": due_at, "priority": priority, "assignee_staff": assignee_staff}
	fingerprint = _fingerprint(payload); command_key = _command_key("manual_action", actor, key)
	if replay := _replay(command_key, fingerprint): return replay
	_lock("CRM Student", student)
	receipt = _new_receipt("action_decision", actor, student, key, fingerprint, scope, frappe.generate_hash(length=20))
	previous_flag = getattr(frappe.flags, "crm_action_command", False); frappe.flags.crm_action_command = True
	try:
		action = frappe.get_doc({"doctype": CANONICAL_ACTION, "student": student, "contact": contact, "origin": "manual", "action_type": action_type, "objective": objective, "disposition": "ACT", "state": "accepted", "execution_status": "planned", "priority": priority, "due_at": due_at, "action_owner": assignee_staff, "source_context_revision": int(student_doc.get("student_context_revision") or 0), "policy_context_version": POLICY_VERSION, "generation_idempotency_key": command_key, "producer_identity": f"user:{actor}", "payload_digest": fingerprint, "accepted_at": now_datetime(), "created_at": now_datetime(), "action_revision": 1, "decision_revision": 1}).insert(ignore_permissions=True)
		result = {"status": "accepted", "action": action.name, "student": student, "revision": action.action_revision, "receipt": receipt.name}
		_finish(receipt, result); return result
	finally:
		frappe.flags.crm_action_command = previous_flag


def _transition_canonical_action(name: str, expected_revision: Any, status: str, idempotency_key: str, correlation_id: str | None = None, outcome_code: str | None = None, evidence: Any = None, reason: str | None = None, linked_interaction: str | None = None, expected_modified: str | None = None):
	"""Transition the single CRM Action aggregate and record its outcome."""
	actor = _actor(); key = _required(idempotency_key, "idempotency_key"); correlation_id = correlation_id or frappe.generate_hash(length=20)
	if status not in {"in_progress", "completed", "failed", "cancelled"}:
		_fail("INVALID_INPUT", "Unsupported Action transition.")
	action = frappe.get_doc(CANONICAL_ACTION, name); scope = _can_decide(actor, action)
	if expected_modified and str(action.modified) != str(expected_modified): _fail("STALE_REVISION", "Action changed; reload before retrying.")
	if str(action.get("action_revision") or 1) != str(expected_revision): _fail("STALE_REVISION", "Action changed; reload before retrying.")
	previous = action.state
	canonical_states = {"accepted": {"in-progress", "cancelled", "deferred"}, "in-progress": {"completed", "requires-review", "cancelled"}}
	target_state = {"in_progress": "in-progress", "completed": "completed", "failed": "requires-review", "cancelled": "cancelled"}[status]
	if target_state not in canonical_states.get(previous, set()): _fail("INVALID_STATE", "Illegal Action transition.")
	if status == "completed":
		if outcome_code not in OUTCOMES: _fail("INVALID_INPUT", "A valid outcome_code is required when completing.")
		_required(evidence, "evidence")
	if status in {"failed", "cancelled"}: _required(reason, "reason")
	payload = {"name": name, "expected_revision": expected_revision, "status": status, "outcome_code": outcome_code, "evidence": evidence, "reason": reason, "linked_interaction": linked_interaction}
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
		if status in {"failed", "cancelled"}: action.terminal_reason = reason
		action.save(ignore_permissions=True)
		event = _event(f"action.{status}", action.student, action.get("recommendation"), action.name, actor, scope, receipt, correlation_id, action.action_revision, {"status": status, "from_state": previous, "outcome_code": outcome_code, "reason": reason})
		_outbox("action.outcome_recorded.v1", action)
		result = {"status": status, "action": action.name, "student": action.student, "revision": action.action_revision, "event": event.name, "receipt": receipt.name}
		_finish(receipt, result); return result
	finally:
		frappe.flags.crm_action_command = previous_flag


def transition_action(name: str, expected_revision: Any, status: str, idempotency_key: str, correlation_id: str | None = None, outcome_code: str | None = None, evidence: Any = None, reason: str | None = None, linked_interaction: str | None = None, expected_modified: str | None = None, _internal_service: bool = False):
	if _internal_service:
		previous_user = frappe.session.user
		frappe.session.user = "Administrator"
		try:
			return _transition_canonical_action(name, expected_revision, status, idempotency_key, correlation_id, outcome_code, evidence, reason, linked_interaction, expected_modified)
		finally:
			frappe.session.user = previous_user
	return _transition_canonical_action(name, expected_revision, status, idempotency_key, correlation_id, outcome_code, evidence, reason, linked_interaction, expected_modified)


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
	_lock(CANONICAL_ACTION, name)
	if replay := _replay(command_key, fingerprint): return replay
	receipt = _new_receipt("action_reassign", actor, action.student, key, fingerprint, scope, correlation_id)
	previous_flag = getattr(frappe.flags, "crm_action_command", False); frappe.flags.crm_action_command = True
	try:
		previous_assignee = action.action_owner
		action.action_owner = assignee_staff
		action.action_revision = int(action.get("action_revision") or 1) + 1
		action.save(ignore_permissions=True)
		event = _event("action.reassigned", action.student, action.get("recommendation"), action.name, actor, scope, receipt, correlation_id, action.action_revision, {"status": action.get("execution_status") or action.state, "previous_assignee": previous_assignee, "assignee_staff": assignee_staff, "reason": reason})
		result = {"status": "reassigned", "action": action.name, "assignee_staff": assignee_staff, "revision": action.action_revision, "event": event.name, "receipt": receipt.name}
		_finish(receipt, result); return result
	finally:
		frappe.flags.crm_action_command = previous_flag


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
