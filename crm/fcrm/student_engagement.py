"""Authoritative Student engagement outcome command service.

The service keeps the append-only outcome stream separate from mutable
``CRM Interaction`` compatibility fields.  It is deliberately small: Task is
the next-action aggregate and all retries are fenced by a command receipt and
the Student engagement revision.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _

from crm.fcrm.qualification import (
	ENGAGEMENT_POLICY_VERSION,
	MEANINGFUL_OUTCOMES,
	OUTCOME_CODES,
	validate_continuity,
	validate_qualification_evidence,
)
from crm.fcrm.record_retention import technical_retention_until
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_contact_conversion import contact_is_linked_to_student, students_for_contact
from crm.fcrm.student_feature_flags import enabled
from crm.fcrm.student_reference import canonical_student

OUTCOME_DOCTYPE = "CRM Student Outcome"
RECEIPT_DOCTYPE = "CRM Student Command Receipt"
SERVICE_FLAG = "student_engagement_service"
CAPABILITY = "outcome.record"
SCHEMA_VERSION = "phase5-v1"


class StudentEngagementError(frappe.ValidationError):
	def __init__(self, code: str, message: str):
		self.code = code
		super().__init__(f"{code}: {message}")


def _fail(code: str, message: str):
	raise StudentEngagementError(code, message)


def _actor() -> str:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		_fail("UNAUTHORIZED", "Authentication is required.")
	return actor


def _authorize(actor: str):
	roles = frappe.get_roles(actor)
	capabilities = capabilities_for_roles(roles, administrator=actor == "Administrator")
	if CAPABILITY not in capabilities and actor != "Administrator":
		_fail("FORBIDDEN", "You are not permitted to record a Student outcome.")
	return {"actor": actor, "roles": sorted(roles), "capabilities": sorted(capabilities)}


def _required(value: Any, label: str) -> str:
	if value in (None, "") or not str(value).strip():
		_fail("INVALID_INPUT", f"{label} is required.")
	return str(value).strip()


def _fingerprint(payload: dict[str, Any]) -> str:
	return hashlib.sha256(
		json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
	).hexdigest()


def _command_key(actor: str, idempotency_key: str) -> str:
	return hashlib.sha256(f"interaction_outcome|{actor}|{idempotency_key}".encode()).hexdigest()


def _receipt(command_key: str, fingerprint: str):
	name = frappe.db.get_value(RECEIPT_DOCTYPE, {"command_key": command_key}, "name")
	if not name:
		return None
	receipt = frappe.get_doc(RECEIPT_DOCTYPE, name)
	if receipt.get("request_fingerprint") not in (None, "", fingerprint):
		_fail("IDEMPOTENCY_KEY_REUSED", "The idempotency key was already used for another request.")
	result = receipt.get("result_json")
	if isinstance(result, str):
		try:
			result = json.loads(result)
		except (TypeError, ValueError):
			result = None
	if isinstance(result, dict):
		result = dict(result)
		result["replayed"] = True
		return result
	return {"status": receipt.get("outcome") or "applied", "receipt": receipt.name, "replayed": True}


def _new_receipt(
	*,
	command_key: str,
	idempotency_key: str,
	fingerprint: str,
	actor: str,
	student: str,
	correlation_id: str | None,
):
	doc = frappe.get_doc(
		{
			"doctype": RECEIPT_DOCTYPE,
			"receipt_key": command_key,
			"command_key": command_key,
			"command_kind": "interaction_outcome",
			"request_fingerprint": fingerprint,
			"outcome": "pending",
			"target_student": student,
			"actor": actor,
			"scope_snapshot": {"actor": actor},
			"policy_version": ENGAGEMENT_POLICY_VERSION,
			"schema_version": SCHEMA_VERSION,
			"correlation_token": correlation_id,
			"request_received_at": frappe.utils.now_datetime(),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _update_receipt(
	receipt, result: dict[str, Any], *, outcome: str = "created", error_code: str | None = None
):
	values = {
		"outcome": outcome,
		"result_json": json.dumps(result, default=str),
		"completed_at": frappe.utils.now_datetime(),
		"retention_until": technical_retention_until("receipt"),
	}
	if error_code:
		values["error_code"] = error_code
	for field, value in values.items():
		if field in {field.fieldname for field in frappe.get_meta(RECEIPT_DOCTYPE).fields}:
			receipt.db_set(field, value, update_modified=False)


def _student(name: str):
	student_name = canonical_student(_required(name, "student"))
	if not student_name:
		_fail("NOT_FOUND", "The Student does not exist.")
	student = frappe.get_doc("CRM Student", student_name)
	if not student.has_permission("read"):
		_fail("OUT_OF_SCOPE", "The Student is outside your current scope.")
	return student


def _verify_linked_records(
	student: str, interaction: str | None, source_doctype: str | None, source_name: str | None
):
	if interaction:
		try:
			interaction_doc = frappe.get_doc("CRM Interaction", interaction)
		except Exception:
			_fail("NOT_FOUND", "The linked Interaction does not exist.")
		if not interaction_doc.has_permission("read") or interaction_doc.get("student") != student:
			_fail("OUT_OF_SCOPE", "The linked Interaction is outside the Student scope.")
	if bool(source_doctype) != bool(source_name):
		_fail("INVALID_INPUT", "source_doctype and source_name must be supplied together.")
	if source_doctype and source_name:
		try:
			source_doc = frappe.get_doc(source_doctype, source_name)
		except Exception:
			_fail("NOT_FOUND", "The source evidence record does not exist.")
		if not source_doc.has_permission("read"):
			_fail("OUT_OF_SCOPE", "The source evidence is outside the Student scope.")
		linked_student = source_doc.get("student")
		if not linked_student and source_doc.get("reference_doctype") in {"CRM Lead", "CRM Student"}:
			linked_student = source_doc.get("reference_docname")
		if not linked_student and source_doc.get("crm_contact"):
			students = students_for_contact(source_doc.get("crm_contact"))
			linked_student = students[0] if len(students) == 1 else None
		if linked_student and linked_student != student:
			_fail("OUT_OF_SCOPE", "The source evidence belongs to another Student.")


def _verify_evidence(student: str, references: list[dict[str, str]]):
	allowed = {
		"CRM Student Outcome",
		"CRM Interaction",
		"Task",
		"CRM Student Lifecycle Event",
		"CRM Intent",
		"CRM Appointment",
		"CRM Student Document",
		"File",
	}
	for reference in references:
		doctype, name = reference.get("doctype"), reference.get("name")
		if doctype not in allowed:
			_fail("INVALID_EVIDENCE", "Evidence type is not allowed for this outcome.")
		try:
			doc = frappe.get_doc(doctype, name)
		except Exception:
			_fail("INVALID_EVIDENCE", "A referenced evidence record does not exist.")
		if not doc.has_permission("read") and doctype not in {
			"CRM Student Outcome",
			"CRM Student Lifecycle Event",
		}:
			_fail("OUT_OF_SCOPE", "A referenced evidence record is outside your scope.")
		linked_student = doc.get("student")
		if not linked_student and doc.get("reference_doctype") in {"CRM Lead", "CRM Student"}:
			linked_student = doc.get("reference_docname")
		if not linked_student and doc.get("attached_to_doctype") in {"CRM Lead", "CRM Student"}:
			linked_student = doc.get("attached_to_name")
		if not linked_student and doc.get("interaction"):
			linked_student = frappe.db.get_value("CRM Interaction", doc.get("interaction"), "student")
		if linked_student != student:
			_fail("OUT_OF_SCOPE", "Evidence belongs to another Student.")


def _lock_student(name: str):
	try:
		frappe.db.sql("select name from `tabCRM Student` where name = %s for update", (name,))
	except Exception:
		pass


def _revision(student) -> int:
	try:
		return int(student.get("engagement_revision") or 0)
	except (TypeError, ValueError):
		_fail("INVALID_REVISION", "Student engagement revision is invalid.")


def _task(next_action: Any, student: str, interaction: str | None, assignee: str | None, due_at: Any):
	is_existing = isinstance(next_action, str)
	if isinstance(next_action, str):
		doc = frappe.get_doc("Task", next_action)
	else:
		payload = dict(next_action or {})
		payload.setdefault("doctype", "Task")
		doc = frappe.get_doc(payload)
	if doc.get("student") not in (None, "", student):
		_fail("INVALID_CONTINUITY", "Next action belongs to a different Student.")
	if doc.get("reference_doctype") in {"CRM Lead", "CRM Student"} and doc.get("reference_docname") not in (
		None,
		"",
		student,
	):
		_fail("INVALID_CONTINUITY", "Next action references a different Student.")
	if is_existing:
		if not doc.has_permission("write"):
			_fail("FORBIDDEN", "You are not permitted to update this next action.")
		if doc.get("student") != student and doc.get("reference_docname") != student:
			_fail("INVALID_CONTINUITY", "An existing next action must already link to the Student.")
	doc.student = student
	if interaction:
		doc.linked_interaction = interaction
	doc.reference_doctype = "CRM Student"
	doc.reference_docname = student
	if assignee:
		doc.assigned_to = assignee
	if due_at:
		doc.due_date = due_at
	if not doc.get("assigned_to") or not doc.get("due_date"):
		_fail("INVALID_CONTINUITY", "A Task next action requires an assignee and due date.")
	if doc.is_new():
		doc.insert(ignore_permissions=True)
	else:
		doc.db_set(
			{
				"student": doc.student,
				"linked_interaction": doc.get("linked_interaction"),
				"reference_doctype": doc.get("reference_doctype"),
				"reference_docname": doc.get("reference_docname"),
				"assigned_to": doc.get("assigned_to"),
				"due_date": doc.get("due_date"),
			},
			update_modified=False,
		)
	return doc


def record_outcome(
	student: str,
	interaction: str | None = None,
	outcome_code: str | None = None,
	continuity_kind: str | None = None,
	next_action: Any = None,
	next_action_assignee: str | None = None,
	next_action_due_at: Any = None,
	continuity_reason: str | None = None,
	continuity_expires_at: Any = None,
	qualification_evidence: Any = None,
	source_doctype: str | None = None,
	source_name: str | None = None,
	source_key: str | None = None,
	expected_revision: Any = None,
	idempotency_key: str | None = None,
	correlation_id: str | None = None,
	supersedes: str | None = None,
):
	"""Record one immutable Student outcome and project compatibility fields."""
	if not enabled("engagement_write"):
		_fail("DISABLED", "Student engagement writes are disabled by rollout policy.")
	actor = _actor()
	scope = _authorize(actor)
	student_doc = _student(student)
	student = student_doc.name
	_verify_linked_records(student, interaction, source_doctype, source_name)
	idempotency_key = _required(idempotency_key, "idempotency_key")
	outcome_code = _required(outcome_code, "outcome_code")
	if expected_revision in (None, ""):
		_fail("INVALID_INPUT", "expected_revision is required.")
	if outcome_code not in OUTCOME_CODES:
		_fail("INVALID_INPUT", "Unknown Student outcome code.")
	payload = {
		"student": student,
		"interaction": interaction,
		"outcome_code": outcome_code,
		"continuity_kind": continuity_kind,
		"next_action": next_action,
		"next_action_assignee": next_action_assignee,
		"next_action_due_at": next_action_due_at,
		"continuity_reason": continuity_reason,
		"continuity_expires_at": continuity_expires_at,
		"qualification_evidence": qualification_evidence,
		"source_doctype": source_doctype,
		"source_name": source_name,
		"source_key": source_key,
		"expected_revision": expected_revision,
		"supersedes": supersedes,
	}
	fingerprint = _fingerprint(payload)
	command_key = _command_key(actor, idempotency_key)
	replayed = _receipt(command_key, fingerprint)
	if replayed:
		return replayed
	if source_key and frappe.db.exists(OUTCOME_DOCTYPE, {"source_key": source_key}):
		existing = frappe.db.get_value(OUTCOME_DOCTYPE, {"source_key": source_key}, "name")
		return {"status": "attached", "event": existing, "student": student, "deduplicated": True}
	receipt = _new_receipt(
		command_key=command_key,
		idempotency_key=idempotency_key,
		fingerprint=fingerprint,
		actor=actor,
		student=student,
		correlation_id=correlation_id,
	)
	_lock_student(student)
	student_doc = _student(student)
	current_revision = _revision(student_doc)
	if expected_revision not in (None, "") and str(expected_revision) != str(current_revision):
		_fail("STALE_REVISION", "Student engagement changed; reload before retrying.")
	next_task = None
	if continuity_kind == "task" and outcome_code in MEANINGFUL_OUTCOMES:
		next_task = _task(next_action, student, interaction, next_action_assignee, next_action_due_at)
	continuity = validate_continuity(
		outcome_code,
		continuity_kind,
		next_action={"student": student, "assigned_to": next_task.assigned_to, "due_date": next_task.due_date}
		if next_task
		else next_action,
		reason=continuity_reason,
		expires_at=continuity_expires_at,
	)
	evidence = validate_qualification_evidence(None, outcome_code, qualification_evidence)["evidence"]
	_verify_evidence(student, evidence)
	if supersedes:
		prior = frappe.get_doc(OUTCOME_DOCTYPE, supersedes)
		if prior.student != student:
			_fail("INVALID_INPUT", "A correction may only supersede an outcome for the same Student.")
		if frappe.db.exists(OUTCOME_DOCTYPE, {"supersedes": supersedes}):
			_fail("INVALID_INPUT", "This outcome has already been superseded.")
	previous_service_flag = getattr(frappe.flags, SERVICE_FLAG, False)
	setattr(frappe.flags, SERVICE_FLAG, True)
	try:
		event_name = frappe.generate_hash(length=20)
		event = frappe.get_doc(
			{
				"doctype": OUTCOME_DOCTYPE,
				"event_id": event_name,
				"student": student,
				"interaction": interaction,
				"outcome_code": outcome_code,
				"continuity_kind": continuity.get("continuity_kind"),
				"next_action": next_task.name if next_task else None,
				"next_action_assignee": next_task.assigned_to if next_task else None,
				"next_action_due_at": next_task.due_date if next_task else None,
				"continuity_reason": continuity_reason,
				"continuity_expires_at": continuity.get("expires_at"),
				"qualification_evidence": json.dumps(evidence),
				"source_doctype": source_doctype,
				"source_name": source_name,
				"source_key": source_key,
				"actor": actor,
				"actor_scope": json.dumps(scope),
				"occurred_at": frappe.utils.now_datetime(),
				"supersedes": supersedes,
				"command_receipt": receipt.name,
				"idempotency_key": idempotency_key,
				"correlation_id": correlation_id,
				"policy_version": ENGAGEMENT_POLICY_VERSION,
				"schema_version": SCHEMA_VERSION,
			}
		).insert(ignore_permissions=True)
		if interaction and frappe.db.exists("CRM Interaction", interaction):
			updates = {"outcome": outcome_code}
			if next_task:
				updates.update(
					{"next_follow_up_date": next_task.due_date, "next_follow_up_action": next_task.title}
				)
			frappe.db.set_value("CRM Interaction", interaction, updates, update_modified=False)
		frappe.db.set_value(
			"CRM Student", student, "engagement_revision", current_revision + 1, update_modified=False
		)
		result = {
			"status": "created",
			"event": event.name,
			"student": student,
			"revision": current_revision + 1,
			"receipt": receipt.name,
		}
		_update_receipt(receipt, result)
		return result
	finally:
		setattr(frappe.flags, SERVICE_FLAG, previous_service_flag)


def supersede_outcome(outcome: str, **kwargs):
	prior = frappe.get_doc(OUTCOME_DOCTYPE, outcome)
	kwargs.update({"student": prior.student, "supersedes": outcome})
	return record_outcome(**kwargs)


def get_outcome_vocabulary() -> dict[str, Any]:
	return {"policy_version": ENGAGEMENT_POLICY_VERSION, "outcomes": sorted(OUTCOME_CODES)}


def get_student_context(
	student: str, history_limit: int = 20, history_cursor: str | None = None
) -> dict[str, Any]:
	"""Compatibility import for the scoped context read service."""
	from crm.fcrm.student_context import get_student_context as _get_context

	return _get_context(student=student, history_limit=history_limit, history_cursor=history_cursor)


# Stable service names used by the Phase 5 API contract.
record_student_outcome = record_outcome


def supersede_student_outcome(**kwargs):
	outcome = kwargs.pop("outcome", None) or kwargs.pop("supersedes", None)
	if not outcome:
		_fail("INVALID_INPUT", "supersedes is required.")
	return supersede_outcome(outcome, **kwargs)
