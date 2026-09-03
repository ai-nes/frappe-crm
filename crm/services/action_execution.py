"""Durable, provider-independent execution-attempt state machine."""

import hashlib
import hmac

import frappe
from frappe.utils import get_datetime, now_datetime

from crm.fcrm.nba import (
	ensure_nba_execution_for_attempt,
	resolve_nba_channel,
	update_nba_execution,
	validate_nba_action_execution,
)
from crm.services.action_execution_contract import TERMINAL, TRANSITIONS, fingerprint


def create_or_replay_attempt(action_name, operation, idempotency_key, expected_action_revision, expected_package_revision):
	if operation not in {"DISPATCH", "SCHEDULE", "RECORD_OUTCOME"}:
		frappe.throw("Unsupported execution operation.", frappe.ValidationError)
	if not idempotency_key or len(idempotency_key) > 180:
		frappe.throw("A valid idempotency key is required.", frappe.ValidationError)
	action = frappe.get_doc("CRM Action", action_name)
	if not action.has_permission("read"):
		frappe.throw("Action is outside the actor's scope.", frappe.PermissionError)
	if action.action_type == "HANDOFF" and operation == "DISPATCH":
		frappe.throw("HANDOFF cannot use the dispatch operation.", frappe.PermissionError)
	if operation == "DISPATCH" and frappe.conf.get("crm_action_pii_controls_enabled", 0) not in (1, "1", True):
		frappe.throw("Outbound execution is disabled until PII controls are enabled.", frappe.PermissionError, title="PII_CONTROLS_REQUIRED")
	if action.state in {"completed", "cancelled", "rejected", "superseded"}:
		frappe.throw("The Action is terminal.", frappe.ValidationError)
	if int(action.action_revision or 1) != int(expected_action_revision):
		frappe.throw("Action changed; refresh before retrying.", frappe.ValidationError, title="STALE_REVISION")
	package_revision = int(action.execution_package_version or 0)
	if package_revision != int(expected_package_revision):
		frappe.throw("Package changed; refresh before retrying.", frappe.ValidationError, title="STALE_REVISION")
	actor = frappe.session.user
	nba_definition = validate_nba_action_execution(action, actor=actor, operation=operation)
	request_fingerprint = fingerprint(action.name, operation, actor, expected_action_revision, expected_package_revision)
	rows = frappe.get_all("CRM Action Execution Attempt", filters={"action": action.name, "idempotency_key": idempotency_key}, fields=["*"])
	if rows:
		attempt = rows[0]
		if attempt.request_fingerprint != request_fingerprint:
			frappe.throw("Idempotency key was already used for another request.", frappe.ValidationError, title="IDEMPOTENCY_MISMATCH")
		return {"status": attempt.status, "attempt_id": attempt.name, "replayed": True, "action": action.name}
	attempt = frappe.get_doc({
		"doctype": "CRM Action Execution Attempt", "action": action.name, "actor": actor,
		"operation": operation, "idempotency_key": idempotency_key, "request_fingerprint": request_fingerprint,
		"status": "pending", "action_revision": int(expected_action_revision),
		"package_revision": package_revision, "attempt_generation": 1, "lease_count": 0,
		"provider_idempotency_key": _provider_key(action.name, operation, idempotency_key),
		"ownership_revision": int(action.get("action_revision") or 0),
		"consent_revision": int(action.get("decision_revision") or 0),
		"policy_revision": str(action.get("policy_context_version") or "unknown"),
		"created_at": now_datetime(),
	}).insert(ignore_permissions=True)
	execution = ensure_nba_execution_for_attempt(attempt, action=action)
	if execution:
		frappe.db.set_value("CRM Action Execution Attempt", attempt.name, "nba_execution", execution.name, update_modified=False)
	if nba_definition and nba_definition.get("auto_execute") and operation == "DISPATCH":
		queued = transition_attempt(attempt.name, "queued")
		return {**queued, "replayed": False, "auto_executed": True, "action": action.name}
	return {"status": "pending", "attempt_id": attempt.name, "replayed": False, "action": action.name}


def _provider_key(action_name, operation, idempotency_key):
	"""Create a stable, bounded provider key without exposing the browser key."""
	value = f"{action_name}:{operation}:{idempotency_key}".encode()
	return "crm-action-" + hashlib.sha256(value).hexdigest()


def authorize_attempt_for_send(attempt_id):
	"""Worker-side, immediately-before-send authorization; never returns recipient data."""
	attempt = frappe.get_doc("CRM Action Execution Attempt", attempt_id)
	if attempt.status != "queued":
		frappe.throw("Only queued attempts may be authorized for send.", frappe.ValidationError)
	action = frappe.get_doc("CRM Action", attempt.action)
	try:
		validate_nba_action_execution(action, actor=attempt.actor, operation=attempt.operation)
	except frappe.PermissionError:
		transition_attempt(attempt_id, "cancelled")
		raise
	if attempt.get("nba_execution"):
		scheduled_at = frappe.db.get_value("CRM Action Execution", attempt.nba_execution, "scheduled_at")
		if scheduled_at and get_datetime(scheduled_at) > now_datetime():
			frappe.throw("The Action Execution is not due yet.", frappe.ValidationError, title="ACTION_EXECUTION_NOT_DUE")
	if not action.has_permission("read") or action.state in {"completed", "cancelled", "rejected", "superseded"}:
		transition_attempt(attempt_id, "cancelled")
		frappe.throw("Action is no longer executable.", frappe.PermissionError)
	if int(action.action_revision or 1) != int(attempt.action_revision) or int(action.execution_package_version or 0) != int(attempt.package_revision):
		transition_attempt(attempt_id, "cancelled")
		frappe.throw("Pinned Action/package revision is stale.", frappe.ValidationError, title="STALE_REVISION")
	if frappe.db.get_value("CRM Student", action.student, "privacy_status") == "opted_out" or (action.get("contact") and frappe.db.get_value("CRM Contact", action.contact, "is_opted_out")):
		transition_attempt(attempt_id, "cancelled")
		frappe.throw("Consent no longer permits this operation.", frappe.PermissionError, title="CONSENT_REQUIRED")
	if not attempt.provider_idempotency_key:
		attempt.provider_idempotency_key = _provider_key(attempt.action, attempt.operation, attempt.idempotency_key)
	attempt.lease_count = int(attempt.lease_count or 0) + 1
	attempt.save(ignore_permissions=True)
	return {"status": "authorized", "attempt_id": attempt.name, "provider_idempotency_key": attempt.provider_idempotency_key}


def process_queued_attempt(attempt_id, channel=None):
	"""Worker entry point: authorize immediately, then call only a registered provider."""
	attempt = frappe.get_doc("CRM Action Execution Attempt", attempt_id)
	action = frappe.get_doc("CRM Action", attempt.action)
	channel = resolve_nba_channel(action, channel)
	if channel not in {"EMAIL", "MESSAGE", "CALL"}:
		frappe.throw("Unsupported provider channel.", frappe.ValidationError)
	result = authorize_attempt_for_send(attempt_id)
	update_nba_execution(attempt_id, status="in_progress", channel=channel, started_at=now_datetime())
	from crm.services.action_provider import send
	try:
		provider_event_id = send(channel, result["provider_idempotency_key"], attempt_id)
	except Exception as exc:
		transition_attempt(attempt_id, "failed")
		update_nba_execution(attempt_id, status="failed", error=str(exc)[:2000], completed_at=now_datetime())
		return {"status": "failed", "attempt_id": attempt_id, "code": "PROVIDER_UNAVAILABLE", "detail": str(exc)[:200]}
	update_nba_execution(attempt_id, output={"provider_event_id": provider_event_id}, provider_event_id=provider_event_id)
	return {"status": "submitted", "attempt_id": attempt_id, "provider_event_id": provider_event_id}


def confirm_provider_event(attempt_id, provider_event_id, signature, raw_body):
	"""Confirm one provider event with signature, uniqueness and generation fencing."""
	if not provider_event_id or not signature:
		frappe.throw("Provider event identity and signature are required.", frappe.ValidationError)
	secret = frappe.conf.get("crm_action_provider_webhook_secret")
	if not secret or not hmac.compare_digest(
		hmac.new(secret.encode(), (raw_body or "").encode(), hashlib.sha256).hexdigest(), signature
	):
		frappe.throw("Invalid provider callback signature.", frappe.PermissionError)
	attempt = frappe.get_doc("CRM Action Execution Attempt", attempt_id)
	if frappe.db.exists("CRM Action Execution Attempt", {"provider_event_id": provider_event_id, "name": ["!=", attempt_id]}):
		return {"status": "duplicate", "attempt_id": attempt.name}
	if attempt.status in TERMINAL:
		return {"status": attempt.status, "attempt_id": attempt.name, "replayed": True}
	transition_attempt(attempt_id, "confirmed", provider_event_id=provider_event_id)
	return {"status": "confirmed", "attempt_id": attempt.name, "provider_event_id": provider_event_id}


def transition_attempt(attempt_id, target_status, *, provider_event_id=None):
	"""Apply one monotonic attempt transition under a row lock."""
	attempt = frappe.get_doc("CRM Action Execution Attempt", attempt_id)
	frappe.db.sql("select name from `tabCRM Action Execution Attempt` where name=%s for update", attempt_id)
	attempt.reload()
	if target_status == "queued":
		action = frappe.get_doc("CRM Action", attempt.action)
		validate_nba_action_execution(action, actor=attempt.actor, operation=attempt.operation)
	if target_status not in TRANSITIONS.get(attempt.status, set()):
		if attempt.status == target_status:
			return {"status": attempt.status, "attempt_id": attempt.name, "replayed": True}
		frappe.throw("Invalid execution attempt transition.", frappe.ValidationError)
	attempt.status = target_status
	if provider_event_id:
		attempt.provider_event_id = provider_event_id
	attempt.lease_count = int(attempt.lease_count or 0) + (1 if target_status == "queued" else 0)
	attempt.save(ignore_permissions=True)
	update_nba_execution(
		attempt.name,
		status={"pending": "pending", "queued": "queued", "confirmed": "in_progress", "failed": "failed", "cancelled": "cancelled"}[attempt.status],
		provider_event_id=provider_event_id,
		completed_at=now_datetime() if attempt.status in {"failed", "cancelled"} else None,
	)
	return {"status": attempt.status, "attempt_id": attempt.name, "replayed": False}


def reconcile_pending_attempts(limit=100):
	"""Return pending attempts for a worker reconciliation pass; no provider call is made here."""
	rows = frappe.get_all("CRM Action Execution Attempt", filters={"status": ["in", ["pending", "queued"]]}, fields=["name", "action", "attempt_generation"], limit_page_length=limit)
	return {"items": rows, "count": len(rows)}
