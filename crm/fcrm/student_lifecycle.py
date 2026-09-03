"""Authoritative Student lifecycle transition command service."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe

from crm.fcrm.qualification import (
	MEANINGFUL_OUTCOMES,
	EVIDENCE_DOCTYPES,
	QUALIFICATION_POLICY_VERSION,
	QualificationValidationError,
	normalize_evidence,
	validate_qualification_evidence,
)
from crm.fcrm.record_retention import technical_retention_until
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_feature_flags import enabled

LIFECYCLE_EVENT_DOCTYPE = "CRM Student Lifecycle Event"
RECEIPT_DOCTYPE = "CRM Student Command Receipt"
POLICY_VERSION = "phase5-lifecycle-v1"
SCHEMA_VERSION = "phase5-v1"
SERVICE_FLAG = "student_lifecycle_service"
ACTIVE_STAGES = ("Lead", "MQL", "Applicant", "Enrolled")
LIFECYCLE_ORDER = ACTIVE_STAGES
LOST_STAGE = "Lost"
FORWARD_EDGES = {stage: ACTIVE_STAGES[index + 1] for index, stage in enumerate(ACTIVE_STAGES[:-1])}


class StudentLifecycleError(frappe.ValidationError):
	def __init__(self, code: str, message: str):
		self.code = code
		super().__init__(f"{code}: {message}")


def _fail(code: str, message: str):
	raise StudentLifecycleError(code, message)


def lifecycle_targets(current_stage: str, capabilities: set[str] | frozenset[str]) -> list[dict[str, Any]]:
	"""Return server-authoritative targets for the transition dialog."""
	if current_stage == LOST_STAGE:
		return [{"stage": "Reopen", "label": "Reopen", "requires_reason": True}] if "lifecycle.reopen" in capabilities else []
	targets = []
	if current_stage in ACTIVE_STAGES and "lifecycle.transition" in capabilities and enabled("lifecycle_write"):
		current_index = ACTIVE_STAGES.index(current_stage)
		for stage in ACTIVE_STAGES[current_index + 1 :]:
			targets.append({"stage": stage, "label": stage, "requires_evidence": True})
	if "lifecycle.lost" in capabilities:
		targets.append({"stage": LOST_STAGE, "label": LOST_STAGE, "requires_reason": True})
	return targets


def validate_transition(current_stage: str, target_stage: str, *, reason: str | None = None, evidence: Any = None, outcome_code: str | None = None, capabilities: set[str] | frozenset[str] = frozenset()) -> dict[str, Any]:
	current = (current_stage or "Lead").strip()
	target = (target_stage or "").strip()
	if target == "Reopen":
		if current != LOST_STAGE:
			_fail("INVALID_EDGE", "Reopen is only valid for a Lost Student.")
		if "lifecycle.reopen" not in capabilities:
			_fail("FORBIDDEN", "You are not permitted to reopen this Student.")
		if not str(reason or "").strip():
			_fail("REASON_REQUIRED", "Reopen requires a reason.")
		return {"from_stage": current, "to_stage": None, "transition_kind": "reopen", "reason": str(reason).strip(), "evidence": []}
	if target == LOST_STAGE:
		if current not in ACTIVE_STAGES:
			_fail("INVALID_EDGE", "Lost can only be entered from an active lifecycle stage.")
		if "lifecycle.lost" not in capabilities:
			_fail("FORBIDDEN", "You are not permitted to mark a Student Lost.")
		if not str(reason or "").strip():
			_fail("REASON_REQUIRED", "Lost requires a reason.")
		return {"from_stage": current, "to_stage": target, "transition_kind": "lost", "reason": str(reason).strip(), "evidence": []}
	if (
		current not in ACTIVE_STAGES
		or target not in ACTIVE_STAGES
		or ACTIVE_STAGES.index(target) <= ACTIVE_STAGES.index(current)
	):
		_fail("INVALID_EDGE", f"{current} cannot transition directly to {target}.")
	if "lifecycle.transition" not in capabilities:
		_fail("FORBIDDEN", "You are not permitted to transition this Student.")
	try:
		validated = validate_qualification_evidence(target, outcome_code, evidence, policy_version=QUALIFICATION_POLICY_VERSION)
	except QualificationValidationError as exc:
		_fail("INVALID_EVIDENCE", str(exc))
	if target in {"MQL", "Applicant", "Enrolled"} and outcome_code in MEANINGFUL_OUTCOMES:
		if not any(
			item["category"] == "outcome" and item["doctype"] == "CRM Student Outcome"
			for item in normalize_evidence(evidence)
		):
			_fail("INVALID_EVIDENCE", "A qualifying CRM Student Outcome record is required.")
	return {"from_stage": current, "to_stage": target, "transition_kind": "forward", "reason": str(reason or "").strip() or None, "evidence": validated["evidence"]}


def _actor() -> str:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		_fail("UNAUTHORIZED", "Authentication is required.")
	return actor


def _capabilities(actor: str):
	roles = frappe.get_roles(actor)
	capabilities = set(capabilities_for_roles(roles, administrator=actor == "Administrator"))
	if actor == "Administrator":
		capabilities.update({"lifecycle.transition", "lifecycle.lost", "lifecycle.reopen", "outcome.record"})
	return capabilities


def _student(name: str):
	student = frappe.get_doc("CRM Student", name)
	if not student.has_permission("read"):
		_fail("OUT_OF_SCOPE", "The Student is outside your current scope.")
	return student


def _verify_evidence(student: str, references: list[dict[str, str]], *, outcome_code: str | None = None):
	outcome_found = False
	for reference in references:
		category, doctype, name = reference.get("category"), reference.get("doctype"), reference.get("name")
		if doctype not in EVIDENCE_DOCTYPES.get(category, frozenset()):
			_fail("INVALID_EVIDENCE", "Evidence type is not allowed for lifecycle qualification.")
		try:
			doc = frappe.get_doc(doctype, name)
		except Exception:
			_fail("INVALID_EVIDENCE", "A referenced qualification record does not exist.")
		if not doc.has_permission("read") and doctype not in {"CRM Student Outcome", "CRM Student Lifecycle Event"}:
			_fail("OUT_OF_SCOPE", "A referenced qualification record is outside your scope.")
		linked_student = doc.get("student")
		if not linked_student and doc.get("reference_doctype") == "CRM Student":
			linked_student = doc.get("reference_docname")
		if not linked_student and doc.get("attached_to_doctype") == "CRM Student":
			linked_student = doc.get("attached_to_name")
		if not linked_student and doc.get("interaction"):
			linked_student = frappe.db.get_value("CRM Interaction", doc.get("interaction"), "student")
		if linked_student != student:
			_fail("OUT_OF_SCOPE", "Qualification evidence belongs to another Student.")
		if category == "outcome":
			outcome_found = True
			if outcome_code and doc.get("outcome_code") != outcome_code:
				_fail("INVALID_EVIDENCE", "The qualifying outcome does not match the requested outcome code.")
	if outcome_code in MEANINGFUL_OUTCOMES and not outcome_found:
		_fail("INVALID_EVIDENCE", "A qualifying CRM Student Outcome record is required.")


def _stage(student) -> str:
	return student.get("lifecycle_stage") or "Lead"


def _revision(student) -> int:
	try:
		return int(student.get("lifecycle_revision") or 0)
	except (TypeError, ValueError):
		_fail("INVALID_REVISION", "Student lifecycle revision is invalid.")


def _command_key(actor: str, idempotency_key: str) -> str:
	return hashlib.sha256(f"lifecycle_transition|{actor}|{idempotency_key}".encode()).hexdigest()


def _fingerprint(payload: dict[str, Any]) -> str:
	return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _replay(command_key: str, fingerprint: str):
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


def _new_receipt(command_key: str, fingerprint: str, student: str, actor: str, correlation_id: str | None):
	doc = frappe.get_doc(
		{
			"doctype": RECEIPT_DOCTYPE,
			"receipt_key": command_key,
			"command_key": command_key,
			"command_kind": "lifecycle_transition",
			"request_fingerprint": fingerprint,
			"outcome": "pending",
			"target_student": student,
			"actor": actor,
			"scope_snapshot": {"actor": actor},
			"policy_version": POLICY_VERSION,
			"schema_version": SCHEMA_VERSION,
			"correlation_token": correlation_id,
			"request_received_at": frappe.utils.now_datetime(),
		}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _finish(receipt, result):
	if "result_json" in {field.fieldname for field in frappe.get_meta(RECEIPT_DOCTYPE).fields}:
		receipt.db_set("result_json", json.dumps(result, default=str), update_modified=False)
	if "outcome" in {field.fieldname for field in frappe.get_meta(RECEIPT_DOCTYPE).fields}:
		receipt.db_set("outcome", "applied", update_modified=False)
	if "completed_at" in {field.fieldname for field in frappe.get_meta(RECEIPT_DOCTYPE).fields}:
		receipt.db_set("completed_at", frappe.utils.now_datetime(), update_modified=False)
	if "retention_until" in {field.fieldname for field in frappe.get_meta(RECEIPT_DOCTYPE).fields}:
		receipt.db_set("retention_until", technical_retention_until("receipt"), update_modified=False)


def _status_for_stage(stage: str) -> str | None:
	rows = frappe.get_all("CRM Term", filters={"category": "enrollment_status"}, fields=["name", "metadata"], order_by="sort_order asc, name asc")
	for row in rows:
		metadata = row.get("metadata") or {}
		if isinstance(metadata, str):
			try:
				metadata = json.loads(metadata)
			except (TypeError, ValueError):
				metadata = {}
		if metadata.get("lifecycle_stage") == stage:
			return row.name
	return frappe.db.get_value(
		"CRM Term",
		{"term_name": {"Lead": "Mới", "MQL": "Có triển vọng", "Applicant": "Đã nộp hồ sơ", "Enrolled": "Đã nhập học", "Lost": "Không quan tâm"}.get(stage), "category": "enrollment_status"},
		"name",
	)


def _lock(name: str):
	try:
		frappe.db.sql("select name from `tabCRM Student` where name = %s for update", (name,))
	except Exception:
		pass


def _prior_active_stage(student: str) -> str | None:
	rows = frappe.get_all(LIFECYCLE_EVENT_DOCTYPE, filters={"student": student}, fields=["from_stage", "to_stage", "prior_active_stage", "transition_kind"], order_by="occurred_at desc, name desc", limit_page_length=20)
	for row in rows:
		if row.get("to_stage") == LOST_STAGE or row.get("transition_kind") == "lost":
			return row.get("from_stage") or row.get("prior_active_stage")
	return None


def request_transition(
	student: str,
	target_stage: str,
	reason: str | None = None,
	evidence_refs: Any = None,
	outcome_code: str | None = None,
	expected_revision: Any = None,
	idempotency_key: str | None = None,
	correlation_id: str | None = None,
):
	if not enabled("lifecycle_write"):
		_fail("DISABLED", "Student lifecycle writes are disabled by rollout policy.")
	actor = _actor()
	capabilities = _capabilities(actor)
	idempotency_key = str(idempotency_key or "").strip()
	if not idempotency_key:
		_fail("INVALID_INPUT", "idempotency_key is required.")
	if expected_revision in (None, ""):
		_fail("INVALID_INPUT", "expected_revision is required.")
	payload = {"student": student, "target_stage": target_stage, "reason": reason, "evidence_refs": evidence_refs, "outcome_code": outcome_code, "expected_revision": expected_revision}
	fingerprint = _fingerprint(payload)
	command_key = _command_key(actor, idempotency_key)
	result = _replay(command_key, fingerprint)
	if result:
		return result
	student_doc = _student(student)
	_lock(student)
	student_doc = _student(student)
	current_stage = _stage(student_doc)
	revision = _revision(student_doc)
	if expected_revision not in (None, "") and str(expected_revision) != str(revision):
		_fail("STALE_REVISION", "Student lifecycle changed; reload before retrying.")
	transition = validate_transition(current_stage, target_stage, reason=reason, evidence=evidence_refs, outcome_code=outcome_code, capabilities=capabilities)
	_verify_evidence(student, transition["evidence"], outcome_code=outcome_code)
	prior_active = _prior_active_stage(student) if transition["transition_kind"] == "reopen" else None
	if transition["transition_kind"] == "reopen":
		if not prior_active:
			_fail("INVALID_STATE", "Lost Student has no recorded prior active stage.")
		transition["to_stage"] = prior_active
	receipt = _new_receipt(command_key, fingerprint, student, actor, correlation_id)
	previous_flag = getattr(frappe.flags, SERVICE_FLAG, False)
	setattr(frappe.flags, SERVICE_FLAG, True)
	try:
		event = frappe.get_doc(
			{
				"doctype": LIFECYCLE_EVENT_DOCTYPE,
				"event_id": frappe.generate_hash(length=20),
				"student": student,
				"from_stage": transition["from_stage"],
				"to_stage": transition["to_stage"],
				"transition_kind": transition["transition_kind"],
				"prior_active_stage": prior_active or (current_stage if transition["transition_kind"] == "lost" else None),
				"reason": transition["reason"],
				"evidence_references": json.dumps(transition["evidence"]),
				"actor": actor,
				"actor_scope": json.dumps({"actor": actor, "capabilities": sorted(capabilities)}),
				"occurred_at": frappe.utils.now_datetime(),
				"command_receipt": receipt.name,
				"idempotency_key": idempotency_key,
				"correlation_id": correlation_id,
				"policy_version": POLICY_VERSION,
				"schema_version": SCHEMA_VERSION,
			}
		).insert(ignore_permissions=True)
		new_revision = revision + 1
		updates = {"lifecycle_stage": transition["to_stage"], "lifecycle_revision": new_revision}
		status = _status_for_stage(transition["to_stage"])
		if status:
			updates["enrollment_status"] = status
		frappe.db.set_value("CRM Student", student, updates, update_modified=False)
		from crm.services.student_context import bump_student_context_revision
		from crm.services.admission_event_policy import admit_lifecycle_transition
		context_change = bump_student_context_revision(
			student, "lifecycle_transition", enqueue=False,
			event_id=f"lifecycle:{event.name}",
		)
		admit_lifecycle_transition(
			student=student,
			revision=context_change["revision"],
			source_event=context_change["change"],
			source_reference=event.name,
		)
		result = {"status": "created", "event": event.name, "student": student, "from_stage": transition["from_stage"], "to_stage": transition["to_stage"], "transition_kind": transition["transition_kind"], "revision": new_revision, "receipt": receipt.name}
		_finish(receipt, result)
		return result
	finally:
		setattr(frappe.flags, SERVICE_FLAG, previous_flag)


def reopen(student: str, reason: str, *, expected_revision: Any = None, idempotency_key: str | None = None, correlation_id: str | None = None):
	return request_transition(student, "Reopen", reason=reason, expected_revision=expected_revision, idempotency_key=idempotency_key, correlation_id=correlation_id)


def get_lifecycle_context(student: str) -> dict[str, Any]:
	actor = _actor()
	student_doc = _student(student)
	capabilities = _capabilities(actor)
	return {"current_stage": _stage(student_doc), "revision": _revision(student_doc), "allowed_targets": lifecycle_targets(_stage(student_doc), capabilities), "policy_version": POLICY_VERSION, "capabilities": {"transition": "lifecycle.transition" in capabilities, "lost": "lifecycle.lost" in capabilities, "reopen": "lifecycle.reopen" in capabilities}}
