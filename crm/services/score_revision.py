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

import re
import time
from collections.abc import Mapping

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
RULESET_IDENTITY_FIELDS = ("rule_version", "rule_version_digest", "ruleset_digest")
_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_RULE_VERSION = re.compile(r"^[A-Z][A-Z0-9._-]{1,63}$")


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


def normalize_score_ruleset_identity(value: Mapping | None, *, allow_empty: bool = False) -> dict[str, str]:
	"""Normalize the immutable ruleset identity carried by scoring work."""
	if value is None:
		value = {}
	if not isinstance(value, Mapping):
		raise ValueError("Score input ruleset identity must be an object.")
	identity = {
		field: str(value.get(field) or "").strip()
		for field in RULESET_IDENTITY_FIELDS
	}
	if not any(identity.values()):
		if allow_empty:
			return {}
		raise ValueError("Score input ruleset identity is required.")
	if not all(identity.values()):
		raise ValueError("Score input ruleset identity must be complete.")
	identity["rule_version"] = identity["rule_version"].upper()
	if not _RULE_VERSION.fullmatch(identity["rule_version"]):
		raise ValueError("Score input rule_version is invalid.")
	for field in ("rule_version_digest", "ruleset_digest"):
		if not _HEX64.fullmatch(identity[field]):
			raise ValueError(f"Score input {field} must be a lowercase SHA-256 digest.")
	if identity["rule_version_digest"] != identity["ruleset_digest"]:
		raise ValueError("Score input ruleset identity digests must agree.")
	return identity


def _score_ruleset_control_plane_configured() -> bool:
	return bool(frappe.db.get_single_value("CRM Rule Settings", "active_rule_version", cache=False))


def _score_input_journal_identity(student: str, revision: int) -> dict[str, str]:
	payload = frappe.db.get_value(
		"CRM Student Revision Journal",
		{
			"student": student,
			"revision": revision,
			"stream": "scoring",
			"event_type": "score_input_changed",
		},
		"payload",
		order_by="creation desc",
	)
	if not payload:
		return {}
	if isinstance(payload, str):
		try:
			payload = frappe.parse_json(payload)
		except Exception as exc:
			raise ValueError("Score input revision journal payload is invalid.") from exc
	if not isinstance(payload, Mapping):
		raise ValueError("Score input revision journal payload is invalid.")
	if payload.get("revision") not in (None, revision):
		raise ValueError("Score input revision journal payload does not match its revision.")
	return normalize_score_ruleset_identity(payload, allow_empty=True)


def _validate_authoritative_score_ruleset(identity: dict[str, str]) -> dict[str, str]:
	"""Verify identity against Frappe's immutable, digest-bound snapshot."""
	if not identity:
		return {}
	from crm.api.rule_engine import _resolve_version_name, _version_wire_catalog

	version_name = _resolve_version_name(identity["rule_version"])
	version = frappe.get_doc("CRM Rule Version", version_name)
	catalog = _version_wire_catalog(version)
	authoritative = {
		"rule_version": str(catalog["rule_version"]).strip().upper(),
		"rule_version_digest": str(catalog["ruleset_digest"]).strip().lower(),
		"ruleset_digest": str(catalog["ruleset_digest"]).strip().lower(),
	}
	if authoritative != identity:
		raise ValueError("Score input ruleset identity does not match the Frappe snapshot.")
	return authoritative


def score_input_ruleset_identity(
	student: str,
	revision: int,
	*,
	supplied: Mapping | None = None,
	require_supplied: bool = False,
) -> dict[str, str]:
	"""Resolve and fence scoring identity against the creation-time journal.

	When the rule control plane exists, a missing creation-time identity is a
	validation failure. A fresh installation without the Settings singleton may
	still settle pre-control-plane historical score rows without inventing an
	identity for them.
	"""
	stored = _score_input_journal_identity(student, revision)
	candidate = normalize_score_ruleset_identity(supplied, allow_empty=True)
	if stored:
		if candidate and candidate != stored:
			raise ValueError("Score input ruleset identity does not match its creation-time identity.")
		if require_supplied and not candidate:
			raise ValueError("Score input ruleset identity is required for CAS write.")
		return _validate_authoritative_score_ruleset(stored)
	if candidate:
		if _score_ruleset_control_plane_configured():
			raise ValueError("Score input has no creation-time ruleset identity.")
		return _validate_authoritative_score_ruleset(candidate)
	if _score_ruleset_control_plane_configured():
		raise ValueError("Score input has no creation-time ruleset identity.")
	return {}


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
	ruleset_identity: dict[str, str] = {}
	if _score_ruleset_control_plane_configured():
		from crm.api.rule_engine import active_ruleset_identity

		try:
			ruleset_identity = normalize_score_ruleset_identity(active_ruleset_identity())
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)
	frappe.db.sql(
		"UPDATE `tabCRM Student` SET score_input_revision = %s WHERE name = %s",
		(revision, student),
	)
	sequence = _next_stream_sequence("scoring")
	event_id = frappe.generate_hash(length=32)
	# The locked row above is authoritative. Avoid Frappe's transient Link-cache
	# miss while this Student's initial insert is still completing.
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
			"payload": {"revision": revision, **ruleset_identity},
			"reason": reason,
			"event_id": event_id,
			"occurred_at": now_datetime(),
		}
	).insert(ignore_permissions=True, ignore_links=True)
	if enqueue and frappe.conf.get("crm_agents_scoring_events_enabled", 0) not in (0, "0", False):
		from crm.api.agent_events import record_score_input_event

		record_score_input_event(student, revision, event_id=event_id, **ruleset_identity)
	return {"student": student, "revision": revision, "stream_sequence": sequence, "change": change.name}
