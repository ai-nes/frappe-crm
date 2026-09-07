"""Student-first, append-only campaign and event attribution commands.

The evidence DocTypes remain deliberately small compatibility projections.  All
new business writes enter here so authority, Student linkage and replay safety
are resolved on the server rather than trusted from a browser payload.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe

from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.record_retention import technical_retention_until
from crm.fcrm.student_contact_conversion import contact_is_linked_to_student

RECEIPT_DOCTYPE = "CRM Student Command Receipt"
SERVICE_FLAG = "student_attribution_service"
CAPABILITY = "attribution.manage"
POLICY_VERSION = "phase7-attribution-v1"
SCHEMA_VERSION = "phase7-v1"


class StudentAttributionError(frappe.ValidationError):
	pass


def get_permission_query_conditions(user=None):
	"""Raw evidence is never a list surface; Student context owns admissions reads."""
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return None
	return "1=0"


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	return user == "Administrator" or "System Manager" in frappe.get_roles(user)


def _fail(code: str, message: str):
	raise StudentAttributionError(f"{code}: {message}")


def _required(value: Any, label: str) -> str:
	if value is None or not str(value).strip():
		_fail("INVALID_INPUT", f"{label} is required.")
	return str(value).strip()


def _actor_and_scope() -> dict[str, Any]:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		_fail("UNAUTHORIZED", "Authentication is required.")
	roles = frappe.get_roles(actor)
	capabilities = capabilities_for_roles(roles, administrator=actor == "Administrator")
	# The admissions command is an already-authorized Student-scoped boundary.
	# It may compose campaign/event evidence for a counselor without granting
	# that counselor unrestricted access to the raw attribution DocTypes.
	if getattr(frappe.flags, "student_admissions_service", False):
		scope = getattr(frappe.flags, "student_admissions_scope", None) or {}
		if scope.get("actor") == actor and scope.get("student"):
			return scope
	if actor != "Administrator" and "System Manager" not in roles and CAPABILITY not in capabilities:
		_fail("FORBIDDEN", "You are not permitted to manage attribution evidence.")
	return {"actor": actor, "roles": sorted(roles), "capabilities": sorted(capabilities)}


def _fingerprint(payload: dict[str, Any]) -> str:
	return hashlib.sha256(
		json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
	).hexdigest()


def _command_key(kind: str, actor: str, idempotency_key: str) -> str:
	return hashlib.sha256(f"{kind}|{actor}|{idempotency_key}".encode()).hexdigest()


def _receipt(command_key: str, fingerprint: str):
	name = frappe.db.get_value(RECEIPT_DOCTYPE, {"command_key": command_key}, "name")
	if not name:
		return None
	receipt = frappe.get_doc(RECEIPT_DOCTYPE, name)
	if receipt.get("request_fingerprint") != fingerprint:
		_fail("IDEMPOTENCY_KEY_REUSED", "The idempotency key was already used for another request.")
	try:
		result = json.loads(receipt.get("result_json") or "{}")
	except (TypeError, ValueError):
		result = {}
	result["status"] = "replayed"
	result["replayed"] = True
	result["receipt"] = receipt.name
	return result


def _new_receipt(*, command_kind: str, command_key: str, fingerprint: str, actor: str, student: str, correlation_id: str | None):
	# Command kind is part of the durable idempotency/audit contract.  Do not
	# collapse attribution writes into an unrelated interaction outcome.
	return frappe.get_doc(
		{
			"doctype": RECEIPT_DOCTYPE,
			"receipt_key": command_key,
			"command_key": command_key,
			"command_kind": command_kind,
			"request_fingerprint": fingerprint,
			"outcome": "pending",
			"target_student": student,
			"actor": actor,
			"scope_snapshot": {"actor": actor, "capability": CAPABILITY},
			"policy_version": POLICY_VERSION,
			"schema_version": SCHEMA_VERSION,
			"correlation_token": correlation_id,
			"request_received_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)


def _complete_receipt(receipt, result: dict[str, Any]):
	for field, value in {
		"outcome": "created",
		"result_json": json.dumps(result, default=str),
		"completed_at": frappe.utils.now_datetime(),
		"retention_until": technical_retention_until("receipt"),
	}.items():
		receipt.db_set(field, value, update_modified=False)


def _student(student: str):
	student = _required(student, "student")
	if not frappe.db.exists("CRM Lead", student):
		_fail("NOT_FOUND", "The Student does not exist.")
	return student


def _linked_contact(student: str, crm_contact: str | None):
	if not crm_contact:
		return None
	if not frappe.db.exists("CRM Student", crm_contact):
		_fail("NOT_FOUND", "The CRM Contact does not exist.")
	if not contact_is_linked_to_student(crm_contact, student):
		_fail("STUDENT_CONTACT_MISMATCH", "The CRM Contact is not linked to this Student.")
	return crm_contact


def _existing_target(doctype: str, name: str, label: str):
	name = _required(name, label)
	if not frappe.db.exists(doctype, name):
		_fail("NOT_FOUND", f"The {label} does not exist.")
	return name


def _validate_supersedes(doctype: str, supersedes: str | None, student: str):
	if not supersedes:
		return None
	prior = frappe.get_doc(doctype, supersedes)
	if prior.get("student") != student:
		_fail("INVALID_SUPERSESSION", "A correction must supersede evidence for the same Student.")
	if frappe.db.exists(doctype, {"supersedes": supersedes}):
		_fail("INVALID_SUPERSESSION", "This evidence has already been superseded.")
	return supersedes


def _record(*, kind: str, student: str, crm_contact: str | None, idempotency_key: str, correlation_id: str | None, supersedes: str | None, values: dict[str, Any]):
	doctype = "CRM Marketing Engagement"
	scope = _actor_and_scope()
	student = _student(student)
	crm_contact = _linked_contact(student, crm_contact)
	idempotency_key = _required(idempotency_key, "idempotency_key")
	payload = {"student": student, "crm_contact": crm_contact, "supersedes": supersedes, **values}
	fingerprint = _fingerprint(payload)
	command_key = _command_key(kind, scope["actor"], idempotency_key)
	if replayed := _receipt(command_key, fingerprint):
		return replayed
	supersedes = _validate_supersedes(doctype, supersedes, student)
	receipt = _new_receipt(command_kind=kind, command_key=command_key, fingerprint=fingerprint, actor=scope["actor"], student=student, correlation_id=correlation_id)
	previous_flag = getattr(frappe.flags, SERVICE_FLAG, False)
	setattr(frappe.flags, SERVICE_FLAG, True)
	try:
		doc = frappe.get_doc({"doctype": doctype, "student": student, "crm_contact": crm_contact, "actor": scope["actor"], "command_receipt": receipt.name, "idempotency_key": idempotency_key, "correlation_id": correlation_id, "supersedes": supersedes, **values})
		doc.insert(ignore_permissions=True)
		result = {"status": "created", "evidence": {"doctype": doctype, "name": doc.name}, "student": student, "receipt": receipt.name, "correlation_id": correlation_id}
		_complete_receipt(receipt, result)
		return result
	finally:
		setattr(frappe.flags, SERVICE_FLAG, previous_flag)


@frappe.whitelist()
def record_campaign_touchpoint(student, crm_campaign, crm_contact=None, touched_at=None, source="Manual", crm_segment=None, notes=None, idempotency_key=None, correlation_id=None, supersedes=None):
	"""Append campaign evidence; retries return the originally created row."""
	_actor_and_scope()
	crm_campaign = _existing_target("CRM Campaign", crm_campaign, "CRM Campaign")
	return _record(kind="campaign_touchpoint", student=student, crm_contact=crm_contact, idempotency_key=idempotency_key, correlation_id=correlation_id, supersedes=supersedes, values={"engagement_kind": "campaign_touch", "reference_doctype": "CRM Campaign", "reference_name": crm_campaign, "crm_campaign": crm_campaign, "touched_at": touched_at or frappe.utils.now_datetime(), "source": source or "Manual", "crm_segment": crm_segment, "notes": notes})


@frappe.whitelist()
def record_event_participation(student, crm_event, crm_contact=None, status="Registered", registered_at=None, checked_in_at=None, feedback_rating=None, feedback_notes=None, idempotency_key=None, correlation_id=None, supersedes=None):
	"""Append event evidence; status corrections supersede rather than mutate."""
	_actor_and_scope()
	crm_event = _existing_target("CRM Event", crm_event, "CRM Event")
	return _record(kind="event_participation", student=student, crm_contact=crm_contact, idempotency_key=idempotency_key, correlation_id=correlation_id, supersedes=supersedes, values={"engagement_kind": "event_participation", "reference_doctype": "CRM Event", "reference_name": crm_event, "crm_event": crm_event, "status": status or "Registered", "registered_at": registered_at or frappe.utils.now_datetime(), "checked_in_at": checked_in_at, "feedback_rating": feedback_rating, "feedback_notes": feedback_notes})


def _redacted_read_authorized():
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor:
		_fail("UNAUTHORIZED", "Authentication is required.")
	roles = frappe.get_roles(actor)
	if actor != "Administrator" and "System Manager" not in roles and CAPABILITY not in capabilities_for_roles(roles):
		_fail("FORBIDDEN", "You are not permitted to view attribution reporting.")


def _metrics(rows):
	students = {row.student for row in rows if row.get("student")}
	metrics = {"students": len(students), "lead": 0, "mql": 0, "applicant": 0, "enrolled": 0, "lost": 0}
	if not students:
		return metrics
	for row in frappe.db.get_all("CRM Lead", filters={"name": ["in", list(students)]}, fields=["enrollment_status"]):
		status = (row.enrollment_status or "").lower()
		if "mql" in status:
			metrics["mql"] += 1
		elif "applicant" in status or "hồ sơ" in status:
			metrics["applicant"] += 1
		elif "enroll" in status or "nhập học" in status:
			metrics["enrolled"] += 1
		elif "lost" in status or "không" in status:
			metrics["lost"] += 1
		else:
			metrics["lead"] += 1
	return metrics


def _page_args(limit, cursor):
	try:
		offset = max(int(cursor or 0), 0)
	except (TypeError, ValueError):
		_fail("INVALID_CURSOR", "cursor must be a non-negative integer token.")
	try:
		limit = int(limit or 100)
	except (TypeError, ValueError):
		limit = 100
	return min(max(limit, 1), 100), offset


def _superseded_page_names(doctype, rows):
	"""Resolve page supersession in one batched query instead of N+1 lookups."""
	names = [row.name for row in rows]
	if not names:
		return set()
	return set(frappe.db.get_all(doctype, filters={"supersedes": ["in", names]}, pluck="supersedes"))


def _student_metrics_for(kind, field, value):
	rows = frappe.db.get_all("CRM Marketing Engagement", filters={"engagement_kind": kind, field: value}, fields=["name", "student"])
	return _metrics(rows)


@frappe.whitelist()
def get_campaign_attribution(crm_campaign, limit=100, cursor=None):
	"""Marketing report with identifiers/timestamps only—never Student snapshots."""
	_redacted_read_authorized()
	crm_campaign = _existing_target("CRM Campaign", crm_campaign, "CRM Campaign")
	limit, offset = _page_args(limit, cursor)
	rows = frappe.db.get_all("CRM Marketing Engagement", filters={"engagement_kind": "campaign_touch", "crm_campaign": crm_campaign}, fields=["name", "student", "touched_at", "source", "supersedes", "creation"])
	rows.sort(key=lambda row: (str(row.touched_at or ""), str(row.creation or ""), str(row.name or "")))
	rows = rows[offset : offset + limit + 1]
	has_next = len(rows) > limit
	page = rows[:limit]
	superseded = _superseded_page_names("CRM Marketing Engagement", page)
	return {"metrics": _student_metrics_for("campaign_touch", "crm_campaign", crm_campaign), "timeline": [{"name": row.name, "student": row.student, "touched_at": row.touched_at, "source": row.source, "superseded": row.name in superseded} for row in page], "next_cursor": str(offset + limit) if has_next else None}


@frappe.whitelist()
def get_event_attribution(crm_event, limit=100, cursor=None):
	"""Marketing report with identifiers/timestamps only—never Student snapshots."""
	_redacted_read_authorized()
	crm_event = _existing_target("CRM Event", crm_event, "CRM Event")
	limit, offset = _page_args(limit, cursor)
	rows = frappe.db.get_all("CRM Marketing Engagement", filters={"engagement_kind": "event_participation", "crm_event": crm_event}, fields=["name", "student", "registered_at", "status", "supersedes", "creation"])
	rows.sort(key=lambda row: (str(row.registered_at or ""), str(row.creation or ""), str(row.name or "")))
	rows = rows[offset : offset + limit + 1]
	has_next = len(rows) > limit
	page = rows[:limit]
	superseded = _superseded_page_names("CRM Marketing Engagement", page)
	return {"metrics": _student_metrics_for("event_participation", "crm_event", crm_event), "timeline": [{"name": row.name, "student": row.student, "registered_at": row.registered_at, "status": row.status, "superseded": row.name in superseded} for row in page], "next_cursor": str(offset + limit) if has_next else None}
