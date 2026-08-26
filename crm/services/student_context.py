"""Frappe-authoritative Student context revision and v2 task primitives."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import frappe
from frappe.utils import now_datetime

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
		"id_number",
		"id_issued_date",
		"id_issued_place",
		"notes",
	}
)


def _next_global_sequence() -> int:
	# MariaDB's named lock closes the empty-table race that a MAX()+1 query
	# alone would leave during the first concurrent material changes.
	frappe.db.sql("SELECT GET_LOCK('crm_student_context_global_sequence', 10)")
	try:
		row = frappe.db.sql(
			"SELECT COALESCE(MAX(global_sequence), 0) + 1 AS next_sequence "
			"FROM `tabCRM Student Context Change`",
			as_dict=True,
		)
		return int(row[0].next_sequence if row else 1)
	finally:
		frappe.db.sql("SELECT RELEASE_LOCK('crm_student_context_global_sequence')")


def bump_student_context_revision(student: str, reason: str, *, enqueue: bool = True) -> dict:
	"""Atomically advance one Student revision and append the global journal."""
	if not student:
		raise ValueError("student is required")
	reason = str(reason or "material_change").strip()[:140] or "material_change"
	row = frappe.db.sql(
		"SELECT student_context_revision FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row:
		raise frappe.DoesNotExistError(f"CRM Student {student} does not exist")
	revision = int(row[0].student_context_revision or 0) + 1
	frappe.db.sql(
		"UPDATE `tabCRM Student` SET student_context_revision = %s WHERE name = %s",
		(revision, student),
	)
	sequence = _next_global_sequence()
	event_id = frappe.generate_hash(length=32)
	change = frappe.get_doc(
		{
			"doctype": "CRM Student Context Change",
			"student": student,
			"revision": revision,
			"global_sequence": sequence,
			"reason": reason,
			"event_id": event_id,
			"occurred_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	if enqueue:
		from crm.api.agent_events import record_student_context_event

		record_student_context_event(student, revision, event_id=event_id)
	return {"student": student, "revision": revision, "global_sequence": sequence, "change": change.name}


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
