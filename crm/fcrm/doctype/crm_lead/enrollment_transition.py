"""Compatibility API that records enrollment status changes as lifecycle events."""

from __future__ import annotations

import hashlib
import json

import frappe

from crm.fcrm.lifecycle import get_lifecycle_stage, lifecycle_rank

DOCTYPE = "CRM Student Lifecycle Event"
RECEIPT_DOCTYPE = "CRM Student Command Receipt"
FAILURE_LOG_TITLE = "CRM Student Lifecycle Event enrollment transition failed"
FAILURE_METRIC_CACHE_KEY = "crm_enrollment_transition_record_failures"


def record_transition(student, old_status, new_status, occurred_at=None, actor=None, source=None):
	"""Record one status change in the typed lifecycle event stream."""
	if old_status == new_status:
		return None
	occurred_at = occurred_at or frappe.utils.now_datetime()
	actor = actor or getattr(frappe.session, "user", None) or "Administrator"

	_run_in_savepoint(lambda: _insert_lifecycle_event(student, old_status, new_status, occurred_at, actor, source))


def set_enrollment_status(doc, new_value, actor=None, source=None):
	"""Set a Student status and route its audit event through ``record_transition``."""
	if isinstance(doc, str):
		doc = frappe.get_doc("CRM Lead", doc)
	old_value = doc.enrollment_status
	if old_value == new_value:
		return doc
	doc.db_set("enrollment_status", new_value)
	record_transition(doc.name, old_value, new_value, actor=actor, source=source or "set_enrollment_status")
	return doc


def _transition_kind(old_stage, new_stage):
	if new_stage == "Lost":
		return "lost"
	if old_stage == "Lost" and new_stage != "Lost":
		return "reopen"
	old_rank, new_rank = lifecycle_rank(old_stage), lifecycle_rank(new_stage)
	if old_rank is not None and new_rank is not None and new_rank < old_rank:
		return "override"
	return "forward"


def _transition_key(student, old_status, new_status, occurred_at, source):
	return hashlib.sha256(
		f"enrollment-transition|{student}|{old_status or ''}|{new_status}|{occurred_at}|{source or ''}".encode()
	).hexdigest()


def _transition_receipt(student, old_status, new_status, occurred_at, actor, source):
	key = _transition_key(student, old_status, new_status, occurred_at, source)
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
			"scope_snapshot": {"source": source or "enrollment_status"},
			"policy_version": "enrollment-transition-v1",
			"schema_version": "enrollment-transition-v1",
			"correlation_token": key,
			"request_received_at": now,
			"completed_at": now,
		}
	).insert(ignore_permissions=True)
	return receipt.name, key


def _insert_lifecycle_event(student, old_status, new_status, occurred_at, actor, source):
	key = _transition_key(student, old_status, new_status, occurred_at, source)
	if frappe.db.exists(DOCTYPE, {"idempotency_key": key}):
		return
	student_doc = frappe.get_doc("CRM Lead", student)
	old_stage = get_lifecycle_stage(old_status)
	new_stage = get_lifecycle_stage(new_status) or student_doc.get("lifecycle_stage") or "Lead"
	receipt, key = _transition_receipt(student, old_status, new_status, occurred_at, actor, source)
	evidence = {
		"old_enrollment_status": old_status,
		"new_enrollment_status": new_status,
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
			"reason": source or "enrollment_status_changed",
			"evidence_references": json.dumps(evidence, sort_keys=True),
			"actor": actor,
			"actor_scope": json.dumps({"source": source or "enrollment_status"}),
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
