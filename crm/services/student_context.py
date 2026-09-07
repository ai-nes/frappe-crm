"""Frappe-authoritative Student context revision and NBA trigger metadata."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import frappe
from frappe.utils import now_datetime

CANONICAL_CONTEXT_POLICY_VERSION = "intelligence-run-nba-v1"

MATERIAL_STUDENT_FIELDS = frozenset(
	{
		"student_name",
		"phone",
		"email",
		"enrollment_status",
		"lifecycle_stage",
		"assigned_to",
		"owner_staff",
		"owning_team",
		"latest_score",
		"enrollment_date",
		"high_school",
		"current_grade",
		"study_stage",
		"province",
		"ward",
		"branch",
		"major",
		"aspiration",
		"step",
		"source",
		"admission_year",
		"cohort_start_year",
		"cohort_end_year",
		"education_program",
		"graduation_score",
		"transcript_score",
		"admission_method",
		"english_converted_score",
		"total_score",
		"alt_name",
		"alt_phone",
		"alt_address",
		"privacy_status",
		"id_number",
		"id_issued_date",
		"id_issued_place",
		"notes",
	}
)


def _next_stream_sequence(stream: str) -> int:
	"""Advance one stream cursor under a row lock; context and scoring do not serialize."""
	frappe.db.sql(
		"INSERT IGNORE INTO `tabCRM Event Stream Cursor` (name, stream, counter, creation, modified, owner, modified_by) VALUES (%s, %s, 0, NOW(), NOW(), %s, %s)",
		(stream, stream, frappe.session.user, frappe.session.user),
	)
	row = frappe.db.sql("SELECT counter FROM `tabCRM Event Stream Cursor` WHERE stream=%s FOR UPDATE", (stream,), as_dict=True)
	sequence = int(row[0].counter or 0) + 1
	frappe.flags.crm_event_stream_cursor_service = True
	try:
		frappe.db.sql("UPDATE `tabCRM Event Stream Cursor` SET counter=%s, modified=NOW() WHERE stream=%s", (sequence, stream))
	finally:
		frappe.flags.crm_event_stream_cursor_service = False
	return sequence


def bump_student_context_revision(student: str, reason: str, *, enqueue: bool = True, event_id: str | None = None) -> dict:
	"""Advance one Student revision without automatically analysing it.

	The revision journal remains the source of truth.  Student 360 is explicit
	refresh only: factual changes make a prior snapshot derived-stale but never
	create an Analysis Run or call an LLM.  ``enqueue`` remains an accepted
	legacy argument so existing producers do not fail during the cutover.
	"""
	if not student:
		raise ValueError("student is required")
	reason = str(reason or "material_change").strip()[:140] or "material_change"
	prior = frappe.db.get_value(
		"CRM Student Revision Journal",
		{"idempotency_key": event_id} if event_id else {},
		["name", "revision", "stream_sequence"],
		as_dict=True,
	) if event_id else None
	if prior:
		return {"student": student, "revision": int(prior.revision), "stream_sequence": int(prior.stream_sequence), "change": prior.name}
	row = frappe.db.sql(
		"SELECT student_context_revision FROM `tabCRM Lead` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row:
		raise frappe.DoesNotExistError(f"CRM Lead {student} does not exist")
	revision = int(row[0].student_context_revision or 0) + 1
	frappe.db.sql(
		"UPDATE `tabCRM Lead` SET student_context_revision = %s WHERE name = %s",
		(revision, student),
	)
	sequence = _next_stream_sequence("context")
	event_id = event_id or frappe.generate_hash(length=32)
	change = frappe.get_doc(
		{
			"doctype": "CRM Student Revision Journal",
			"event_type": "context_changed",
			"stream": "context",
			"student": student,
			"revision": revision,
			"stream_sequence": sequence,
			"actor": frappe.session.user,
			"actor_scope": {"source": "student_context"},
			"idempotency_key": event_id,
			"correlation_id": event_id,
			"policy_version": CANONICAL_CONTEXT_POLICY_VERSION,
			"schema_version": "revision-journal-v1",
			"payload": {"revision": revision},
			"reason": reason,
			"event_id": event_id,
			"occurred_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	result = {"student": student, "revision": revision, "stream_sequence": sequence, "change": change.name}
	return result


def material_student_changed(doc, before=None) -> bool:
	"""Return whether an update changed an authoritative Student field."""
	if before is None:
		return True
	return any(before.get(field) != doc.get(field) for field in MATERIAL_STUDENT_FIELDS)


def mark_student_context_changed(student: str, reason: str) -> dict | None:
	if not student:
		return None
	return bump_student_context_revision(student, reason)


def snapshot_hash(value: dict) -> str:
	body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
	return hashlib.sha256(body.encode()).hexdigest()


def is_committed_task_state(state: str | None) -> bool:
	"""States representing a Sales decision already made on this task.

	A new context revision must never silently supersede one of these -- it
	flags the task REQUIRES_REVIEW instead (see `upsert_student_next_task`).
	DEFERRED and REJECTED are decisions just like ACCEPTED/COMPLETED/
	CANCELLED, not an absence of one; a deferred task in particular carries a
	`revisit_at` that would otherwise vanish from the worklist the moment the
	student's context changes again, before it was ever revisited.
	"""
	return state in {
		"ACCEPTED",
		"IN_PROGRESS",
		"REQUIRES_REVIEW",
		"COMPLETED",
		"CANCELLED",
		"DEFERRED",
		"REJECTED",
	}
