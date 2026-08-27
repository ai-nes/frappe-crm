"""Scoped, redacted read model for critical Student transitions.

This is deliberately *not* another event store and does not feed
``student_context.history``.  Domain event rows remain owned by their phase;
this module adapts the small, reviewed portion of each row into a common audit
envelope.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.role_policy import capabilities_for_roles

POLICY_VERSION = "P9-DEC-001"
CURSOR_VERSION = "critical-transition-v1"
MAX_PAGE_SIZE = 100
SOURCE_FETCH_LIMIT = 250

# The adapter descriptions are the source-contract manifests for the read
# facade.  Hashes are derived from this reviewed, versioned manifest rather
# than from mutable event payloads.
SOURCE_MANIFESTS = (
	{"source": "ownership", "doctype": "CRM Student Ownership Event", "time": "event_at", "kind": "event_type", "family": "ownership"},
	{"source": "sla", "doctype": "CRM Student SLA Event", "time": "event_at", "kind": "event_type", "family": "sla"},
	{"source": "outcome", "doctype": "CRM Student Outcome", "time": "occurred_at", "kind": "outcome_code", "family": "outcome"},
	{"source": "lifecycle", "doctype": "CRM Student Lifecycle Event", "time": "occurred_at", "kind": "transition_kind", "family": "lifecycle"},
	{"source": "decision", "doctype": "CRM Student Decision Event", "time": "occurred_at", "kind": "event_type", "family": "decision"},
	{"source": "attribution", "doctype": "CRM Campaign Touchpoint", "time": "touched_at", "kind": "touch_type", "family": "attribution"},
	{"source": "participation", "doctype": "CRM Event Participation", "time": "registered_at", "kind": "status", "family": "attribution"},
	{"source": "conversion", "doctype": "CRM Student Contact Conversion", "time": "converted_at", "kind": None, "family": "conversion"},
)
SOURCE_CONTRACT_HASH = hashlib.sha256(json.dumps(SOURCE_MANIFESTS, sort_keys=True).encode()).hexdigest()


def _value(row: Any, key: str, default: Any = None) -> Any:
	return row.get(key, default) if hasattr(row, "get") else getattr(row, key, default)


def _fields(doctype: str) -> set[str]:
	try:
		return {field.fieldname for field in frappe.get_meta(doctype).fields}
	except Exception:
		return set()


def _table_exists(doctype: str) -> bool:
	try:
		return bool(frappe.db.table_exists(doctype))
	except Exception:
		return False


def _secret() -> bytes:
	try:
		from frappe.utils.password import get_encryption_key

		return f"crm-critical-transition:{get_encryption_key()}".encode()
	except Exception:
		return b"crm-critical-transition"


def _opaque(value: Any) -> str | None:
	"""Return a non-reversible stable reference; never expose raw event IDs."""
	if value in (None, ""):
		return None
	return "ref_" + hmac.new(_secret(), str(value).encode(), hashlib.sha256).hexdigest()[:20]


def _encode_cursor(payload: dict[str, Any]) -> str:
	body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
	signature = hmac.new(_secret(), body, hashlib.sha256).digest()
	return ".".join(base64.urlsafe_b64encode(part).rstrip(b"=").decode() for part in (body, signature))


def _decode_cursor(cursor: str | None, student: str) -> dict[str, Any] | None:
	if not cursor:
		return None
	try:
		body_token, signature_token = cursor.split(".", 1)
		body = base64.urlsafe_b64decode(body_token + "=" * (-len(body_token) % 4))
		signature = base64.urlsafe_b64decode(signature_token + "=" * (-len(signature_token) % 4))
		if not hmac.compare_digest(signature, hmac.new(_secret(), body, hashlib.sha256).digest()):
			raise ValueError
		payload = json.loads(body)
		if payload.get("v") != CURSOR_VERSION or payload.get("student") != student or not all(
			isinstance(payload.get(key), str) for key in ("as_of", "occurred_at", "source", "event_id")
		):
			raise ValueError
		return payload
	except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
		frappe.throw(_("Invalid critical-transition timeline cursor."), frappe.ValidationError)


def _limit(value: int | str | None) -> int:
	try:
		result = 20 if value in (None, "") else int(value)
	except (TypeError, ValueError):
		frappe.throw(_("limit must be an integer."), frappe.ValidationError)
	if not 1 <= result <= MAX_PAGE_SIZE:
		frappe.throw(_("limit must be between 1 and {0}.").format(MAX_PAGE_SIZE), frappe.ValidationError)
	return result


def _can_read_student(student: str) -> bool:
	if not student:
		return False
	try:
		return bool(frappe.has_permission("CRM Student", "read", student))
	except Exception:
		try:
			return bool(frappe.get_doc("CRM Student", student).has_permission("read"))
		except Exception:
			return False


def _reason_allowed() -> bool:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if actor == "Administrator":
		return True
	try:
		return "student.audit.reason.read" in capabilities_for_roles(frappe.get_roles(actor))
	except Exception:
		return False


def _read_source(manifest: dict[str, Any], student: str, as_of: str, cursor_payload: dict[str, Any] | None = None) -> tuple[list[Any], str | None]:
	"""Read an adapter defensively.  A source outage is reported, not hidden."""
	doctype = manifest["doctype"]
	if not _table_exists(doctype):
		return [], "source_unavailable"
	available = _fields(doctype) | {"name", "creation"}
	if "student" not in available or manifest["time"] not in available:
		return [], "student_scope_unavailable"
	required = {"name", "student", "creation", manifest["time"], "event_id", "actor", "actor_scope", "scope_snapshot", "supersedes", "correlation_id", "correlation_token", "idempotency_key", "event_type", "outcome_code", "transition_kind", "from_stage", "to_stage", "from_state", "to_state", "status", "touch_type", "contact", "action", "recommendation", "command_receipt", "evidence_reference", "evidence_references"}
	fields = sorted(required & available)
	if "name" not in fields:
		fields.append("name")
	try:
		event_key = "COALESCE(`event_id`, `name`)" if "event_id" in available else "`name`"
		where = ["student = %s"]
		params: list[Any] = [student]
		if "creation" in available:
			where.append("creation <= %s")
			params.append(as_of)
		if cursor_payload:
			cursor_time = cursor_payload["occurred_at"]
			cursor_source = cursor_payload["source"]
			if manifest["source"] < cursor_source:
				where.append(f"`{manifest['time']}` <= %s")
				params.append(cursor_time)
			elif manifest["source"] == cursor_source:
				where.append(f"(`{manifest['time']}` < %s OR (`{manifest['time']}` = %s AND {event_key} < %s))")
				params.extend([cursor_time, cursor_time, cursor_payload["event_id"]])
			else:
				where.append(f"`{manifest['time']}` < %s")
				params.append(cursor_time)
		columns = ", ".join(f"`{field}`" for field in fields)
		query = (
			f"SELECT {columns} FROM `tab{doctype}` WHERE {' AND '.join(where)} "
			f"ORDER BY `{manifest['time']}` DESC, {event_key} DESC LIMIT %s"
		)
		params.append(SOURCE_FETCH_LIMIT + 1)
		rows = frappe.db.sql(query, params, as_dict=True)
		return rows[:SOURCE_FETCH_LIMIT], None
	except Exception:
		return [], "source_query_failed"


def _event_type(manifest: dict[str, Any], row: Any) -> str:
	kind = _value(row, manifest.get("kind") or "")
	if manifest["source"] == "conversion":
		return "conversion.completed"
	return f"{manifest['source']}.{kind or 'recorded'}"


def _sanitize_state(manifest: dict[str, Any], row: Any) -> dict[str, str] | None:
	# Explicitly list only code/state fields. JSON payloads and free text are
	# intentionally not decoded or passed through.
	if manifest["family"] == "lifecycle":
		return {key: str(_value(row, key)) for key in ("from_stage", "to_stage") if _value(row, key) not in (None, "")} or None
	if manifest["family"] == "decision":
		return {key: str(_value(row, key)) for key in ("from_state", "to_state") if _value(row, key) not in (None, "")} or None
	if manifest["family"] == "outcome":
		return {"outcome_code": str(_value(row, "outcome_code"))} if _value(row, "outcome_code") else None
	return None


def _adapt(manifest: dict[str, Any], row: Any, student: str, allow_restricted: bool) -> dict[str, Any] | None:
	occurred_at = _value(row, manifest["time"])
	event_id = _value(row, "event_id") or _value(row, "name")
	if not occurred_at or not event_id:
		return None
	event = {
		"event_type": _event_type(manifest, row),
		"student": student,
		"occurred_at": str(occurred_at),
		"event_id": _opaque(event_id),
		"source": manifest["source"],
		"state": _sanitize_state(manifest, row),
		"correlation": _opaque(_value(row, "correlation_id") or _value(row, "correlation_token") or _value(row, "idempotency_key")),
		"supersedes": _opaque(_value(row, "supersedes")),
		"redaction_policy_version": POLICY_VERSION,
		"source_contract_hash": SOURCE_CONTRACT_HASH,
		# Internal tuple members are retained only for signed cursor construction.
		"_cursor_event_id": str(event_id),
	}
	if allow_restricted:
		event["actor"] = _opaque(_value(row, "actor"))
		scope_snapshot = _value(row, "actor_scope") or _value(row, "scope_snapshot")
		if scope_snapshot:
			event["authority_scope"] = _opaque(scope_snapshot)
		for field in ("command_receipt", "action", "recommendation", "evidence_reference", "evidence_references"):
			if _value(row, field):
				event.setdefault("evidence", {})[field] = _opaque(_value(row, field))
	return event


def _sort_key(event: dict[str, Any]) -> tuple[str, str, str]:
	return str(event["occurred_at"]), str(event["source"]), str(event["_cursor_event_id"])


def critical_transition_timeline(student: str, limit: int | str = 20, cursor: str | None = None) -> dict[str, Any]:
	"""Return a scoped, read-only page of normalized critical transitions.

	The current Student permission is checked before every source query.  The
	returned completeness report is part of the contract: clients must not treat
	a response with failed sources as a complete audit record.
	"""
	if not _can_read_student(student):
		frappe.throw(_("You do not have permission to view this Student."), frappe.PermissionError)
	page_size = _limit(limit)
	cursor_payload = _decode_cursor(cursor, student)
	as_of = cursor_payload["as_of"] if cursor_payload else str(now_datetime())
	allow_restricted = _reason_allowed()
	events: list[dict[str, Any]] = []
	omitted_sources: list[dict[str, str]] = []
	for manifest in SOURCE_MANIFESTS:
		if not _can_read_student(student):
			frappe.throw(_("Student scope changed while loading the timeline."), frappe.PermissionError)
		rows, failure = _read_source(manifest, student, as_of, cursor_payload)
		if failure:
			omitted_sources.append({"source": manifest["source"], "reason": failure})
			continue
		for row in rows:
			event = _adapt(manifest, row, student, allow_restricted)
			if event:
				events.append(event)
	events.sort(key=_sort_key, reverse=True)
	if cursor_payload:
		cursor_key = (cursor_payload["occurred_at"], cursor_payload["source"], cursor_payload["event_id"])
		events = [event for event in events if _sort_key(event) < cursor_key]
	page = events[:page_size]
	next_cursor = None
	if len(events) > page_size and page:
		last = page[-1]
		next_cursor = _encode_cursor({"v": CURSOR_VERSION, "student": student, "as_of": as_of, "occurred_at": last["occurred_at"], "source": last["source"], "event_id": last["_cursor_event_id"]})
	serialized_page = [{key: value for key, value in event.items() if key != "_cursor_event_id"} for event in page]
	return {
		"student": student,
		"timeline": serialized_page,
		"next_cursor": next_cursor,
		"as_of": as_of,
		"late_event_policy": "Rows ingested after as_of appear only in a new timeline read.",
		"redaction_policy_version": POLICY_VERSION,
		"source_contract_hash": SOURCE_CONTRACT_HASH,
		"completeness": {"version": CURSOR_VERSION, "complete": not omitted_sources, "omitted_sources": omitted_sources},
	}
