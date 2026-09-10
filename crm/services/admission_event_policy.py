"""Deterministic, Frappe-owned admission for automatic Student Runs.

This module records bounded decisions synchronously with the authoritative
business write.  It never reads notes/payloads or calls an LLM.
"""
from __future__ import annotations

import frappe

POLICY_VERSION = "admission"
TERMINAL_ACTION_STATUSES = {"completed", "failed", "cancelled"}
INTERACTION_FIELDS = {"source_verified", "outcome"}
INTENT_FIELDS = {"intent_type", "intent_role", "polarity", "confidence"}


def _mode() -> str:
	mode = str(frappe.conf.get("crm_admission_event_policy_mode") or "shadow").strip().lower()
	if mode not in {"shadow", "unified"}:
		frappe.throw("Invalid admission event policy mode.", frappe.ValidationError)
	return mode


def _decision(*, student: str, source_event: str, event_type: str, revision: int,
			  source_reference: str | None, outcome: str, reason: str) -> str:
	key = f"{POLICY_VERSION}:{source_event}"
	existing = frappe.db.get_value("CRM Admission Event Decision", {"decision_key": key}, "name")
	if existing:
		return existing
	doc = frappe.get_doc({
		"doctype": "CRM Admission Event Decision", "decision_id": frappe.generate_hash(length=32),
		"decision_key": key, "source_event": source_event, "source_reference": source_reference,
		"event_type": event_type, "student": student, "candidate_revision": int(revision),
		"policy_version": POLICY_VERSION, "outcome": outcome, "reason": reason,
	})
	try:
		doc.insert(ignore_permissions=True)
	except Exception as exc:
		if "duplicate" not in str(exc).casefold() and "unique" not in str(exc).casefold():
			raise
		return frappe.db.get_value("CRM Admission Event Decision", {"decision_key": key}, "name") or ""
	# Admission remains an auditable factual decision.  It must not enqueue a
	# Student 360 LLM run: Sales explicitly refreshes the analytical snapshot.
	return doc.name


def evaluate_admission_event(*, student: str, revision: int, source_event: str,
						 event_type: str, source_reference: str | None = None) -> str:
	"""Record one idempotent decision, admitting only the current revision."""
	if not student or not source_event:
		return ""
	_mode()  # fail closed on an invalid rollout mode before any write
	current = frappe.db.sql("SELECT student_context_revision FROM `tabCRM Student` WHERE name=%s FOR UPDATE", (student,), as_dict=True)
	if not current:
		return ""
	current_revision = int(current[0].student_context_revision or 0)
	if current_revision != int(revision):
		return _decision(student=student, source_event=source_event, event_type=event_type,
						 revision=revision, source_reference=source_reference, outcome="superseded", reason="superseded")
	return _decision(student=student, source_event=source_event, event_type=event_type,
					 revision=revision, source_reference=source_reference, outcome="admitted", reason="enqueued")


def _student_for(doc):
	return doc.get("student") or (frappe.db.get_value("CRM Student", doc.get("crm_contact"), "student") if doc.get("crm_contact") else None)


def admit_interaction(doc, method=None):
	student = _student_for(doc)
	if not student or not (doc.get("source_verified") or doc.get("outcome")):
		return
	previous = doc.get_doc_before_save() if not doc.is_new() else None
	if previous and not any(previous.get(field) != doc.get(field) for field in INTERACTION_FIELDS):
		return
	from crm.services.student_context import bump_student_context_revision
	identity = f"interaction:{doc.name}:{int(bool(doc.get('source_verified')))}:{doc.get('outcome') or ''}"
	# Replay is deduped downstream: `bump_student_context_revision` returns the
	# prior journal for a repeated `event_id`, so `_decision` sees a stable key.
	change = bump_student_context_revision(student, "interaction_material_change", enqueue=False, event_id=identity)
	evaluate_admission_event(student=student, revision=change["revision"], source_event=change["change"], event_type="interaction", source_reference=doc.name)


def admit_intent(doc, method=None):
	if not doc.get("student"):
		return
	previous = doc.get_doc_before_save() if not doc.is_new() else None
	if previous and not any(previous.get(field) != doc.get(field) for field in INTENT_FIELDS):
		return
	from crm.services.student_context import bump_student_context_revision
	identity = "intent:" + doc.name + ":" + ":".join(str(doc.get(field) or "") for field in sorted(INTENT_FIELDS))
	change = bump_student_context_revision(doc.student, "intent_material_change", enqueue=False, event_id=identity)
	evaluate_admission_event(student=doc.student, revision=change["revision"], source_event=change["change"], event_type="intent", source_reference=doc.name)


def admit_action_outcome(*, student: str, revision: int, source_event: str, source_reference: str):
	return evaluate_admission_event(student=student, revision=revision, source_event=source_event,
								event_type="action_outcome", source_reference=source_reference)


def admit_lifecycle_transition(*, student: str, revision: int, source_event: str, source_reference: str):
	return evaluate_admission_event(student=student, revision=revision, source_event=source_event,
								event_type="lifecycle_transition", source_reference=source_reference)
