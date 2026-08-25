"""Phase 6 recommendation decisions and Sales Action command service.

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
ACTION = "CRM Sales Action"
POLICY_VERSION = "phase6-v1"
SCHEMA_VERSION = "phase6-v1"
OUTCOMES = {"NO_RESPONSE", "INTEREST_INCREASED", "NEEDS_MORE_INFORMATION", "CALL_BACK_LATER", "APPLICATION_STARTED", "APPLICATION_COMPLETED", "NOT_INTERESTED"}
ACTION_TRANSITIONS = {"planned": {"in_progress", "cancelled"}, "in_progress": {"completed", "failed", "cancelled"}}


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
	if not ({"student.execute", "sales_action.execute"} & set(
		capabilities_for_roles(frappe.get_roles(user), administrator=user == "Administrator")
	)):
		_fail("INVALID_INPUT", "The selected executor is not an approved Sales Action executor.")
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


def _can_execute(actor, action):
	scope = _scope(actor)
	if actor == "Administrator":
		return scope
	if not ({"student.execute", "sales_action.execute"} & set(scope["capabilities"])):
		_fail("FORBIDDEN", "You are not permitted to execute Sales Actions.")
	if not action.has_permission("read"):
		_fail("OUT_OF_SCOPE", "The Sales Action is outside your current scope.")
	if action.assignee_staff != _staff_for_user(actor) and "team.oversee" not in scope["capabilities"] and "admissions.oversee" not in scope["capabilities"]:
		_fail("FORBIDDEN", "Only the assigned executor may update this Sales Action.")
	return scope


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
		"command_kind": kind if kind in {"recommendation_decision", "sales_action", "sales_action_reassign"} else "interaction_outcome",
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


def _event(kind, student, recommendation, action, actor, scope, receipt, correlation_id, revision, payload):
	"""Write audit evidence only when the Phase 6 contract was migrated."""
	if not _exists(DECISION_EVENT):
		_fail("CONTRACT_UNAVAILABLE", "CRM Student Decision Event is not migrated; Phase 6 writes are unavailable.")
	fields = _meta_fields(DECISION_EVENT)
	event_type = "recommendation_decided" if kind.startswith("recommendation.") else {
		"sales_action.in_progress": "action_started",
		"sales_action.reassigned": "action_reassigned",
		"sales_action.completed": "action_completed",
		"sales_action.failed": "action_failed",
		"sales_action.cancelled": "action_cancelled",
	}.get(kind, "action_superseded")
	values = {"doctype": DECISION_EVENT, "event_id": frappe.generate_hash(length=20), "student": student,
		"recommendation": recommendation, "sales_action": action, "event_type": event_type, "actor": actor,
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
			action = frappe.db.get_value(ACTION, {"recommendation": doc.name}, "name")
			if not action:
				action_doc = frappe.get_doc({"doctype": ACTION, "recommendation": doc.name, "student": doc.student, "action_type": doc.recommended_action, "created_at": now_datetime(), "due_at": due_at, "assignee_staff": assignee_staff, "assignee_snapshot": {"assignee": assignee_staff, "student": doc.student}, "assignment_history": [], "assignment_revision": 1, "action_revision": 1, "correlation_id": correlation_id, "idempotency_key": key, "execution_status": "planned"})
				action_doc.flags.from_phase6_command = True; action_doc.insert(ignore_permissions=True); action = action_doc.name
		event = _event(f"recommendation.{status}", doc.student, doc.name, action, actor, scope, receipt, correlation_id, doc.decision_revision, {"status": status, "from_state": previous_status, "reason": decision_reason, "revisit_at": str(revisit_at) if revisit_at else None})
		_outbox("recommendation.decided.v1", event)
		result = {"status": status, "recommendation": doc.name, "sales_action": action, "revision": doc.decision_revision, "event": event.name, "receipt": receipt.name}; _finish(receipt, result); return result
	finally:
		frappe.flags.phase6_decision_command = previous_flag


def transition_sales_action(name: str, expected_revision: Any, status: str, idempotency_key: str, correlation_id: str | None = None, outcome_code: str | None = None, evidence: Any = None, reason: str | None = None, linked_interaction: str | None = None, expected_modified: str | None = None, _internal_service: bool = False):
	actor = "Administrator" if _internal_service else _actor(); key = _required(idempotency_key, "idempotency_key"); correlation_id = correlation_id or frappe.generate_hash(length=20)
	payload = {"name": name, "expected_revision": expected_revision, "status": status, "outcome_code": outcome_code, "evidence": evidence, "reason": reason, "linked_interaction": linked_interaction}
	fingerprint = _fingerprint(payload); command_key = _command_key("sales_action", actor, key)
	if replay := _replay(command_key, fingerprint): return replay
	_lock(ACTION, name)
	if replay := _replay(command_key, fingerprint): return replay
	action = frappe.get_doc(ACTION, name); scope = _can_execute(actor, action)
	if expected_modified and str(action.modified) != str(expected_modified): _fail("STALE_REVISION", "Sales Action changed; reload before retrying.")
	if str(action.get("action_revision") or 1) != str(expected_revision): _fail("STALE_REVISION", "Sales Action changed; reload before retrying.")
	if status not in ACTION_TRANSITIONS.get(action.execution_status, set()): _fail("INVALID_STATE", "Illegal Sales Action transition.")
	if status == "completed":
		if outcome_code not in OUTCOMES:
			_fail("INVALID_INPUT", "A valid outcome_code is required when completing.")
		_required(evidence, "evidence")
	if status in {"failed", "cancelled"}: _required(reason, "reason")
	if status == "completed" and linked_interaction and not frappe.db.exists(
		"CRM Student Outcome", {"student": action.student, "interaction": linked_interaction, "correlation_id": correlation_id}
	):
		_fail("INVALID_INPUT", "Linked CRM Interaction requires a same-correlation Phase 5 Student Outcome.")
	previous_status = action.execution_status
	receipt = _new_receipt("sales_action", actor, action.student, key, fingerprint, scope, correlation_id)
	previous_flag = getattr(frappe.flags, "phase6_decision_command", False); frappe.flags.phase6_decision_command = True
	try:
		action.flags.from_phase6_command = True; action.execution_status = status; action.action_revision = int(action.get("action_revision") or 1) + 1
		if status == "in_progress": action.started_at = now_datetime()
		if status == "completed": action.completed_at = now_datetime(); action.outcome_code = outcome_code; action.business_outcome = outcome_code; action.outcome_at = now_datetime(); action.outcome_actor = actor; action.outcome_evidence = evidence; action.outcome_notes = evidence if isinstance(evidence, str) else None; action.linked_interaction = linked_interaction
		if status in {"failed", "cancelled"}: action.terminal_reason = reason
		action.save(ignore_permissions=True)
		event = _event(f"sales_action.{status}", action.student, action.recommendation, action.name, actor, scope, receipt, correlation_id, action.action_revision, {"status": status, "from_state": previous_status, "outcome_code": outcome_code, "reason": reason})
		_outbox("sales_action.outcome_recorded.v1", event)
		result = {"status": status, "sales_action": action.name, "student": action.student, "revision": action.action_revision, "event": event.name, "receipt": receipt.name}; _finish(receipt, result); return result
	finally:
		frappe.flags.phase6_decision_command = previous_flag


def reassign_sales_action(name: str, expected_revision: Any, assignee_staff: str, idempotency_key: str, reason: str, correlation_id: str | None = None, _internal_service: bool = False):
	"""CAS/idempotent reassignment used by ownership changes and authorized leads."""
	actor = "Administrator" if _internal_service else _actor()
	key = _required(idempotency_key, "idempotency_key")
	reason = _required(reason, "reason")
	correlation_id = correlation_id or frappe.generate_hash(length=20)
	payload = {"name": name, "expected_revision": expected_revision, "assignee_staff": assignee_staff, "reason": reason}
	fingerprint = _fingerprint(payload); command_key = _command_key("sales_action_reassign", actor, key)
	if replay := _replay(command_key, fingerprint): return replay
	_lock(ACTION, name)
	if replay := _replay(command_key, fingerprint): return replay
	action = frappe.get_doc(ACTION, name); scope = _scope(actor)
	if actor != "Administrator" and "sales_action.reassign" not in scope["capabilities"]:
		_fail("FORBIDDEN", "You are not permitted to reassign Sales Actions.")
	if actor != "Administrator" and not action.has_permission("read"):
		_fail("OUT_OF_SCOPE", "The Sales Action is outside your current scope.")
	if str(action.get("action_revision") or 1) != str(expected_revision):
		_fail("STALE_REVISION", "Sales Action changed; reload before retrying.")
	if action.execution_status not in {"planned", "in_progress"}:
		_fail("INVALID_STATE", "Only active Sales Actions may be reassigned.")
	_valid_executor(action.student, assignee_staff, allow_global=actor == "Administrator")
	receipt = _new_receipt("sales_action_reassign", actor, action.student, key, fingerprint, scope, correlation_id)
	previous_flag = getattr(frappe.flags, "phase6_decision_command", False); frappe.flags.phase6_decision_command = True
	try:
		action.flags.from_phase6_command = True
		previous_assignee = action.assignee_staff
		action.assignee_staff = assignee_staff
		history = action.get("assignment_history") or []
		action.assignment_history = [*history, {"from": previous_assignee, "to": assignee_staff, "actor": actor, "reason": reason, "at": str(now_datetime())}]
		action.assignment_revision = int(action.get("assignment_revision") or 0) + 1
		action.action_revision = int(action.get("action_revision") or 1) + 1
		action.save(ignore_permissions=True)
		event = _event("sales_action.reassigned", action.student, action.recommendation, action.name, actor, scope, receipt, correlation_id, action.action_revision, {"status": action.execution_status, "from_state": action.execution_status, "previous_assignee": previous_assignee, "assignee_staff": assignee_staff, "reason": reason})
		# Reassignment uses the existing action projection signal; consumers
		# re-read the authoritative action and observe the Decision Event type.
		_outbox("sales_action.outcome_recorded.v1", event)
		result = {"status": "reassigned", "sales_action": action.name, "assignee_staff": assignee_staff, "revision": action.action_revision, "event": event.name, "receipt": receipt.name}
		_finish(receipt, result); return result
	finally:
		frappe.flags.phase6_decision_command = previous_flag


def reconcile_student_actions(student: str, next_owner_staff: str | None, next_owning_team: str | None, correlation_id: str):
	"""Reconcile active work after an authoritative Student ownership change."""
	rows = frappe.get_all(ACTION, filters={"student": student, "execution_status": ["in", ["planned", "in_progress"]]}, fields=["name", "action_revision"])
	for row in rows:
		key = f"ownership-reconcile-{correlation_id}-{row.name}"
		if next_owner_staff:
			try:
				reassign_sales_action(row.name, row.action_revision or 1, next_owner_staff, key, "Student ownership changed; action reassigned to current owner.", correlation_id, _internal_service=True)
			except StudentDecisionError:
				transition_sales_action(row.name, row.action_revision or 1, "cancelled", key + "-cancel", correlation_id=correlation_id, reason="Student ownership changed and no executable owner was available.", _internal_service=True)
		else:
			transition_sales_action(row.name, row.action_revision or 1, "cancelled", key + "-cancel", correlation_id=correlation_id, reason="Student ownership moved to an unassigned team pool.", _internal_service=True)
