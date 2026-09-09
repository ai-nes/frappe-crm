"""Canonical Student intake command gateway.

Only this module is exposed to Desk/REST callers.  Actor, profile and scope are
resolved by :mod:`crm.fcrm.student_intake`; request fields never carry an
authority grant.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from crm.fcrm.student_contact_conversion import contact_for_student
from crm.fcrm.student_intake import StudentIntakeError
from crm.fcrm.student_intake import decide_intake_review as _decide_intake_review
from crm.fcrm.student_intake import submit_intake as _submit_intake

CONTACT_SOURCE_SYSTEMS = frozenset({"chatwoot", "offline_capture"})
_AUTHORITY_FIELDS = frozenset(
	{
		"actor",
		"actor_user",
		"profile",
		"roles",
		"campus_scope",
		"team_scope",
		"capability",
		"signed",
		"owner_staff",
	}
)
_CONTACT_FIELD_MAP = {
	"full_name": "student_name",
	"phone": "phone",
	"email": "email",
	"province_code": "province",
	"high_school_code": "high_school",
	"major_code": "major",
	"study_stage": "study_stage",
	"lead_source": "source",
	"campaign_code": "campaign_code",
	"event_code": "event_code",
	"captured_at": "captured_at",
	"consent": "consent",
	"raw_payload": "raw_payload",
}


def _fail(code: str, message: str):
	raise StudentIntakeError(code, message)


def _normalize_contact_payload(payload: dict[str, Any]) -> dict[str, Any]:
	if not isinstance(payload, dict):
		_fail("INVALID_INPUT", "Payload must be a JSON object.")
	for fieldname in _AUTHORITY_FIELDS:
		if fieldname in payload:
			_fail("INVALID_INPUT", f"{fieldname} is server-owned.")

	source_system = str(payload.get("source_system") or payload.get("source_namespace") or "").strip()
	if source_system not in CONTACT_SOURCE_SYSTEMS:
		_fail("INVALID_INPUT", "source_system must be chatwoot or offline_capture.")
	if payload.get("source_system") and "consent" not in payload:
		_fail("INVALID_INPUT", "consent is required for external contact intake.")
	external_id = str(payload.get("external_id") or payload.get("source_record_id") or "").strip()
	if not source_system or not external_id:
		_fail("INVALID_INPUT", "source_system and external_id are required.")
	if len(source_system) > 64 or len(external_id) > 120:
		_fail("INVALID_INPUT", "Contact source identifiers exceed their size limits.")
	idempotency_key = payload.get("idempotency_key")
	if idempotency_key is not None and len(str(idempotency_key)) > 140:
		_fail("INVALID_INPUT", "Contact idempotency_key exceeds its size limit.")

	canonical = {
		"source_namespace": source_system,
		"source_record_id": external_id,
	}
	for source, target in _CONTACT_FIELD_MAP.items():
		if source in payload:
			canonical[target] = payload[source]
	if "idempotency_key" in payload:
		canonical["idempotency_key"] = payload["idempotency_key"]
	if "correlation_id" in payload:
		canonical["correlation_id"] = payload["correlation_id"]
	if "campus" in payload:
		canonical["campus"] = payload["campus"]
	if "owning_team" in payload:
		canonical["owning_team"] = payload["owning_team"]
	for fieldname in (
		"student_name",
		"admission_year",
		"admission_cycle",
		"year",
		"national_id",
		"id_number",
		"cccd",
		"mobile",
		"telephone",
		"advertising_channel",
		"current_grade",
		"study_stage",
		"gender",
		"date_of_birth",
		"alt_name",
		"alt_phone",
	):
		if fieldname in payload:
			canonical[fieldname] = payload[fieldname]
	return canonical


def _contact_for_student(student_id: str | None) -> str | None:
	if not student_id:
		return None
	try:
		return contact_for_student(student_id)
	except Exception:
		return None


def _intake_response(result: dict[str, Any]) -> dict[str, Any]:
	student_id = result.get("student")
	response = {
		"student_id": student_id,
		"contact_id": _contact_for_student(student_id),
		"status": result.get("outcome"),
		"receipt_id": result.get("receipt"),
	}
	# The Desk review modal consumes these server-masked fields immediately after
	# intake. Do not collapse a review-required command into a generic status.
	for fieldname in ("review_id", "candidates", "proposed_identity", "error_code"):
		if fieldname in result:
			response[fieldname] = result[fieldname]
	return response


def _normalize_manual_payload(payload: dict[str, Any]) -> dict[str, Any]:
	"""Unwrap the Desk modal command without applying external-source rules."""
	manual = payload.get("payload")
	if not isinstance(manual, dict):
		_fail("INVALID_INPUT", "Manual intake payload must be a JSON object.")
	canonical = dict(manual)
	canonical["source_namespace"] = "crm.manual_intake"
	canonical["source_record_id"] = payload.get("source_record_id")
	canonical["idempotency_key"] = payload.get("idempotency_key")
	if payload.get("correlation_id"):
		canonical["correlation_id"] = payload["correlation_id"]
	if not canonical["source_record_id"] or not canonical["idempotency_key"]:
		_fail("INVALID_INPUT", "source_record_id and idempotency_key are required.")
	return canonical


def _request_json(payload: Any = None):
	if payload is not None:
		return payload
	try:
		return frappe.request.get_json(silent=True)
	except Exception:
		return None


@frappe.whitelist(methods=["POST"])
def submit_intake(
	payload: dict[str, Any] | str | None = None,
	source_namespace: str | None = None,
	source_record_id: str | None = None,
	idempotency_key: str | None = None,
	correlation_id: str | None = None,
	expected_review_id: str | None = None,
) -> dict[str, Any]:
	"""Submit a Student intake command through the server policy gateway."""
	payload = _request_json(payload)
	if not isinstance(payload, (dict, str)):
		_fail("INVALID_INPUT", "Payload must be a JSON object.")
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except ValueError:
			_fail("INVALID_INPUT", "Payload must be a valid JSON object.")
	if not isinstance(payload, dict):
		_fail("INVALID_INPUT", "Payload must be a JSON object.")
	# frappe-ui sends the nested form as the ``payload`` argument and the
	# command identifiers as sibling RPC args. Support that normal Frappe call
	# shape as well as a JSON envelope supplied by an API client.
	manual_source = source_namespace or payload.get("source_namespace")
	if manual_source == "crm.manual_intake":
		manual_envelope = payload
		if not isinstance(payload.get("payload"), dict):
			manual_envelope = {
				"payload": payload,
				"source_namespace": source_namespace,
				"source_record_id": source_record_id,
				"idempotency_key": idempotency_key,
				"correlation_id": correlation_id,
			}
		canonical = _normalize_manual_payload(manual_envelope)
		result = _submit_intake(
			canonical,
			source_namespace=canonical["source_namespace"],
			source_record_id=str(canonical["source_record_id"]),
			idempotency_key=str(canonical["idempotency_key"]),
			correlation_id=canonical.get("correlation_id"),
			expected_review_id=expected_review_id,
			request_payload=payload,
		)
		return _intake_response(result)
	if "consent" not in payload:
		_fail("INVALID_INPUT", "consent is required for external contact intake.")
	adapter_payload = dict(payload)
	if (
		source_namespace
		and "source_system" not in adapter_payload
		and "source_namespace" not in adapter_payload
	):
		adapter_payload["source_namespace"] = source_namespace
	if (
		source_record_id
		and "external_id" not in adapter_payload
		and "source_record_id" not in adapter_payload
	):
		adapter_payload["source_record_id"] = source_record_id
	if idempotency_key and "idempotency_key" not in adapter_payload:
		adapter_payload["idempotency_key"] = idempotency_key
	canonical = _normalize_contact_payload(adapter_payload)
	if source_namespace and source_namespace != canonical["source_namespace"]:
		_fail("INVALID_INPUT", "source_namespace does not match source_system.")
	if source_record_id and source_record_id != canonical["source_record_id"]:
		_fail("INVALID_INPUT", "source_record_id does not match external_id.")
	if idempotency_key:
		canonical["idempotency_key"] = idempotency_key
	if correlation_id:
		canonical["correlation_id"] = correlation_id
	if not canonical.get("idempotency_key"):
		_fail("INVALID_INPUT", "idempotency_key is required.")
	result = _submit_intake(
		canonical,
		source_namespace=canonical["source_namespace"],
		source_record_id=canonical["source_record_id"],
		idempotency_key=canonical["idempotency_key"],
		correlation_id=canonical.get("correlation_id"),
		expected_review_id=expected_review_id,
		request_payload=payload,
	)
	return _intake_response(result)


@frappe.whitelist(methods=["POST"])
def decide_intake_review(
	review_id: str,
	decision: str,
	evidence_refs: list[str] | str | None = None,
	reason: str | None = None,
	idempotency_key: str | None = None,
	correlation_id: str | None = None,
	expected_revision: int | str | None = None,
	identity_data: dict[str, Any] | None = None,
	expected_review_id: str | None = None,
	evidence: list[str] | str | None = None,
	identity_id: str | None = None,
) -> dict[str, Any]:
	"""Apply one authorized, durable intake review decision."""
	if isinstance(identity_data, str):
		try:
			identity_data = json.loads(identity_data)
		except ValueError:
			frappe.throw("INVALID_INPUT: identity_data must be a JSON object", frappe.ValidationError)
	if identity_data is not None and not isinstance(identity_data, dict):
		frappe.throw("INVALID_INPUT: identity_data must be a JSON object", frappe.ValidationError)
	if expected_review_id and expected_review_id != review_id:
		frappe.throw("STALE_REVISION: review identity changed", frappe.ValidationError)
	if evidence_refs is None:
		evidence_refs = evidence
	if reason is None and isinstance(evidence, str):
		reason = evidence
	return _decide_intake_review(
		review_id,
		decision,
		evidence_refs,
		reason,
		idempotency_key,
		correlation_id,
		expected_revision,
		identity_data=identity_data,
		identity_id=identity_id,
	)
