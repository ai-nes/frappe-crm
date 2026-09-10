"""Compatibility API that records Student stage changes as lifecycle events."""

from __future__ import annotations

import hashlib
import json

import frappe

from crm.fcrm.student_stage import (
	STUDENT_STAGES,
	set_student_stage,
	stage_from_enrollment_status,
)

DOCTYPE = "CRM Student Lifecycle Event"
RECEIPT_DOCTYPE = "CRM Student Command Receipt"
FAILURE_LOG_TITLE = "CRM Student Lifecycle Event enrollment transition failed"
FAILURE_METRIC_CACHE_KEY = "crm_enrollment_transition_record_failures"


def record_transition(student, old_stage, new_stage, occurred_at=None, actor=None, source=None):
	"""Record one Student stage change in the typed event stream."""
	if old_stage == new_stage:
		return None
	occurred_at = occurred_at or frappe.utils.now_datetime()
	actor = actor or getattr(frappe.session, "user", None) or "Administrator"

	_run_in_savepoint(lambda: _insert_lifecycle_event(student, old_stage, new_stage, occurred_at, actor, source))


def set_enrollment_status(doc, new_value, actor=None, source=None):
	"""Compatibility wrapper; callers must now provide a canonical Student stage."""
	if isinstance(doc, str):
		doc = frappe.get_doc("CRM Student", doc)
	target = new_value if new_value in STUDENT_STAGES else stage_from_enrollment_status(new_value)
	set_student_stage(doc.name, target, _internal_service=True)
	return frappe.get_doc("CRM Student", doc.name)


def _transition_kind(old_stage, new_stage):
	if new_stage == "Disqualified":
		return "lost"
	if old_stage == "Disqualified" and new_stage != "Disqualified":
		return "reopen"
	return "forward"


def _transition_key(student, old_stage, new_stage, occurred_at, source):
	return hashlib.sha256(
		f"student-stage-transition|{student}|{old_stage or ''}|{new_stage}|{occurred_at}|{source or ''}".encode()
	).hexdigest()


def _transition_receipt(student, old_stage, new_stage, occurred_at, actor, source):
	key = _transition_key(student, old_stage, new_stage, occurred_at, source)
	existing = frappe.db.get_value(RECEIPT_DOCTYPE, {"command_key": key}, "name")
	if existing:
		return existing, key
	now = frappe.utils.now_datetime()
	receipt = frappe.get_doc(
		{
			"doctype": RECEIPT_DOCTYPE,
			"receipt_key": key,
			"command_key": key,
			"command_kind": "lifecycle_transition",
			"request_fingerprint": key,
			"outcome": "created",
			"target_student": student,
			"actor": actor,
			"scope_snapshot": {"source": source or "student_stage"},
			"policy_version": "enrollment-transition-v1",
			"schema_version": "enrollment-transition-v1",
			"correlation_token": key,
			"request_received_at": now,
			"completed_at": now,
		}
	).insert(ignore_permissions=True)
	return receipt.name, key


def _insert_lifecycle_event(student, old_stage, new_stage, occurred_at, actor, source):
	key = _transition_key(student, old_stage, new_stage, occurred_at, source)
	if frappe.db.exists(DOCTYPE, {"idempotency_key": key}):
		return
	receipt, key = _transition_receipt(student, old_stage, new_stage, occurred_at, actor, source)
	evidence = {
		"old_stage": old_stage,
		"new_stage": new_stage,
		"source": source,
		"occurred_at": str(occurred_at),
	}
	frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"event_id": f"enrollment:{key[:24]}",
			"student": student,
			"from_stage": old_stage,
			"to_stage": new_stage,
			"transition_kind": _transition_kind(old_stage, new_stage),
			"reason": source or "student_stage_changed",
			"evidence_references": json.dumps(evidence, sort_keys=True),
			"actor": actor,
			"actor_scope": json.dumps({"source": source or "student_stage"}),
			"occurred_at": occurred_at,
			"command_receipt": receipt,
			"idempotency_key": key,
			"correlation_id": key,
			"policy_version": "enrollment-transition-v1",
			"schema_version": "enrollment-transition-v1",
		}
	).insert(ignore_permissions=True)
	from crm.services.student_context import bump_student_context_revision
	change = bump_student_context_revision(student, "lifecycle_transition", enqueue=False, event_id=f"lifecycle:{key}")
	from crm.services.admission_event_policy import admit_lifecycle_transition
	admit_lifecycle_transition(student=student, revision=change["revision"], source_event=change["change"], source_reference=receipt)


def _run_in_savepoint(fn):
	savepoint_name = "crm_enrollment_transition_" + frappe.generate_hash(length=10)
	try:
		frappe.db.sql(f"SAVEPOINT {savepoint_name}")
	except Exception:
		try:
			fn()
		except Exception:
			_record_failure()
		return
	try:
		fn()
		frappe.db.sql(f"RELEASE SAVEPOINT {savepoint_name}")
	except Exception:
		frappe.db.sql(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
		_record_failure()


def _record_failure():
	frappe.log_error(title=FAILURE_LOG_TITLE, message=frappe.get_traceback())
	try:
		frappe.cache().incrby(FAILURE_METRIC_CACHE_KEY, 1)
	except Exception:
		pass


def reconcile_enrollment_transitions():
	"""Retained scheduler entry point; lifecycle events are now canonical."""
	return {"status": "canonical_lifecycle_events", "mismatches": 0}
