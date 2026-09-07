"""Scoring-relevant Student revision.

`score_input_revision` is a narrower sibling of `student_context_revision`
(`crm.services.student_context`): it increments only for facts the *currently
active* scoring policy actually consumes, so an assignment/ownership change or
any other non-scoring Student edit never triggers a rescore. Mirrors the same
row-lock + global-sequence-journal + outbox pattern as
`bump_student_context_revision`, on an independent revision counter and an
independent outbox event type, so scoring cannot collide with or be starved by
unrelated Student-context traffic.
"""

from __future__ import annotations

import time

import frappe
from frappe.utils import now_datetime

from crm.fcrm.scoring_policy import get_active_policy

# Fixed synthetic condition_field names resolved from Student child tables by
# app/services/scoring/evaluator.py's SignalContext.get_field(), not read
# directly off a CRM Student column. A property rule configured against one of
# these must still be treated as consuming this Student's academic child rows.
_CHILD_TABLE_CONDITION_FIELDS = frozenset({"grade", "gpa", "academic_rank", "ielts_score"})
_ACADEMIC_CHILD_TABLES = frozenset({"academic_results", "language_certificates"})

_POLICY_FIELDS_CACHE_TTL_S = 60
_policy_fields_cache: dict = {}


def score_relevant_condition_fields(*, refresh: bool = False) -> frozenset:
	"""Condition fields the active policy's property rules actually read.

	Cached briefly (not per-request) since this is read on every Student save;
	a stale cache only delays a revision bump by at most the TTL, it never
	causes an incorrect calculation (the calculation itself always re-resolves
	the live active policy, per `get_active_policy()`).
	"""
	now = time.monotonic()
	if not refresh and _policy_fields_cache.get("at", 0) + _POLICY_FIELDS_CACHE_TTL_S > now:
		return _policy_fields_cache["fields"]
	policy = get_active_policy()
	fields = frozenset(
		rule["condition_field"]
		for rule in (policy or {}).get("rules", [])
		if rule.get("condition_field")
	)
	_policy_fields_cache["fields"] = fields
	_policy_fields_cache["at"] = now
	return fields


def student_score_input_changed(doc, before=None) -> bool:
	"""Return whether a Student save changed a fact the active policy consumes."""
	if before is None:
		return True
	fields = score_relevant_condition_fields()
	if any(before.get(field) != doc.get(field) for field in fields if hasattr(doc, field)):
		return True
	if fields & _CHILD_TABLE_CONDITION_FIELDS:
		for table in _ACADEMIC_CHILD_TABLES:
			if _child_rows_changed(table, before.get(table) or [], doc.get(table) or []):
				return True
	return False


# Only these child-row fields feed a scorer's condition_field (see
# evaluator.py's _latest_academic/_best_gpa_row/_ielts_score) -- comparing the
# whole row would also flag unrelated metadata (idx, modified, ...) as a change.
_ACADEMIC_ROW_FIELDS = ("school_year", "grade", "gpa", "academic_rank")
_LANGUAGE_ROW_FIELDS = ("language", "certificate_name", "score_level")
_ACADEMIC_TABLE_ROW_FIELDS = {
	"academic_results": _ACADEMIC_ROW_FIELDS,
	"language_certificates": _LANGUAGE_ROW_FIELDS,
}


def _child_rows_changed(table: str, before_rows: list, after_rows: list) -> bool:
	if len(before_rows) != len(after_rows):
		return True
	fields = _ACADEMIC_TABLE_ROW_FIELDS[table]
	before_key = sorted(tuple(row.get(f) for f in fields) for row in before_rows)
	after_key = sorted(tuple(row.get(f) for f in fields) for row in after_rows)
	return before_key != after_key


def _next_stream_sequence(stream: str) -> int:
	frappe.db.sql(
		"INSERT IGNORE INTO `tabCRM Event Stream Cursor` (name, stream, counter, creation, modified, owner, modified_by) VALUES (%s, %s, 0, NOW(), NOW(), %s, %s)",
		(stream, stream, frappe.session.user, frappe.session.user),
	)
	row = frappe.db.sql("SELECT counter FROM `tabCRM Event Stream Cursor` WHERE stream=%s FOR UPDATE", (stream,), as_dict=True)
	sequence = int(row[0].counter or 0) + 1
	frappe.db.sql("UPDATE `tabCRM Event Stream Cursor` SET counter=%s, modified=NOW() WHERE stream=%s", (sequence, stream))
	return sequence


def bump_score_input_revision(student: str, reason: str, *, enqueue: bool = True) -> dict:
	"""Atomically advance one Student's score_input_revision and journal it."""
	if not student:
		raise ValueError("student is required")
	reason = str(reason or "scoring_fact_change").strip()[:140] or "scoring_fact_change"
	row = frappe.db.sql(
		"SELECT score_input_revision FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row:
		raise frappe.DoesNotExistError(f"CRM Student {student} does not exist")
	revision = int(row[0].score_input_revision or 0) + 1
	frappe.db.sql(
		"UPDATE `tabCRM Student` SET score_input_revision = %s WHERE name = %s",
		(revision, student),
	)
	sequence = _next_stream_sequence("scoring")
	event_id = frappe.generate_hash(length=32)
	change = frappe.get_doc(
		{
			"doctype": "CRM Student Revision Journal",
			"event_type": "score_input_changed",
			"stream": "scoring",
			"student": student,
			"revision": revision,
			"stream_sequence": sequence,
			"actor": frappe.session.user,
			"actor_scope": {"source": "score_revision"},
			"idempotency_key": event_id,
			"correlation_id": event_id,
			"policy_version": "score-input-v2",
			"schema_version": "revision-journal-v1",
			"payload": {"revision": revision},
			"reason": reason,
			"event_id": event_id,
			"occurred_at": now_datetime(),
		}
	).insert(ignore_permissions=True)
	if enqueue and frappe.conf.get("crm_agents_scoring_events_enabled", 0) not in (0, "0", False):
		from crm.api.agent_events import record_score_input_event

		record_score_input_event(student, revision, event_id=event_id)
	return {"student": student, "revision": revision, "stream_sequence": sequence, "change": change.name}
