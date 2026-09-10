"""Signed external ingress for Student intake.

The adapter authenticates the raw request bytes and replay tuple before the
canonical command sees the payload. It deliberately never logs or stores the
raw body; receipts retain an opaque fingerprint and bounded encrypted
provenance alongside the command outcome.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

import frappe

from crm.api.student_intake import _intake_response, _normalize_contact_payload
from crm.fcrm.student_intake import StudentIntakeError, _secret_versions, body_fingerprint, submit_intake

TIMESTAMP_WINDOW_SECONDS = 300
SIGNATURE_HEADER = "X-CRM-Intake-Signature"
TIMESTAMP_HEADER = "X-CRM-Intake-Timestamp"
NONCE_HEADER = "X-CRM-Intake-Nonce"
NAMESPACE_HEADER = "X-CRM-Intake-Source"
RECORD_HEADER = "X-CRM-Intake-Record"
IDEMPOTENCY_HEADER = "X-CRM-Intake-Idempotency-Key"
CORRELATION_HEADER = "X-CRM-Intake-Correlation-Id"


def _header(name: str, default: str | None = None) -> str | None:
	try:
		return frappe.request.headers.get(name) or frappe.request.headers.get(name.lower()) or default
	except Exception:
		return default


def _raw_body() -> bytes:
	try:
		body = frappe.request.get_data(cache=True, as_text=False)
	except Exception:
		body = b""
	if isinstance(body, str):
		return body.encode("utf-8")
	return body or b""


def signing_message(raw_body: bytes, source_namespace: str, timestamp: str, nonce: str) -> bytes:
	"""Canonical bytes signed by providers.

	Length prefixes make the namespace/timestamp/nonce tuple unambiguous and
	prevent a body boundary from being moved between signed components.
	"""
	from crm.fcrm.student_intake import encode_key

	return encode_key("crm.student.intake.webhook.v1", raw_body, source_namespace, timestamp, nonce)


def _configured_sources() -> dict[str, Any]:
	try:
		value = frappe.conf.get("student_intake_webhook_sources")
	except Exception:
		value = None
	if isinstance(value, dict):
		return value
	return {}


def _source_secret(namespace: str) -> list[tuple[str, bytes]]:
	configured = _configured_sources().get(namespace)
	if isinstance(configured, dict) and configured.get("secret"):
		secret = configured["secret"]
		if isinstance(secret, dict):
			return [(str(version), str(value).encode("utf-8")) for version, value in secret.items() if value]
		return [("v1", str(secret).encode("utf-8"))]
	if configured and isinstance(configured, str):
		return [("v1", configured.encode("utf-8"))]
	return _secret_versions()


def _source_context(namespace: str) -> dict[str, Any]:
	configured = _configured_sources().get(namespace)
	if not isinstance(configured, dict) or not configured.get("secret"):
		_raise_replay("REPLAY_REJECTED", "The source namespace is not configured.")
	if not configured.get("campus_scope") or not configured.get("team_scope"):
		_raise_replay("REPLAY_REJECTED", "The source namespace has no configured Campus/Team scope.")
	return {
		"actor_user": configured.get("actor_user") if isinstance(configured, dict) else "Signed Ingress",
		"actor_staff": configured.get("actor_staff") if isinstance(configured, dict) else None,
		"campus_scope": configured.get("campus_scope", []) if isinstance(configured, dict) else [],
		"team_scope": configured.get("team_scope", []) if isinstance(configured, dict) else [],
	}


def _raise_replay(code: str, message: str):
	raise StudentIntakeError(code, message)


def verify_signature(
	raw_body: bytes, source_namespace: str, timestamp: str, nonce: str, provided: str
) -> str:
	if not source_namespace or not timestamp or not nonce or not provided:
		_raise_replay("REPLAY_REJECTED", "Signed ingress headers are incomplete.")
	try:
		stamp = int(timestamp)
	except (TypeError, ValueError):
		_raise_replay("REPLAY_REJECTED", "Signed ingress timestamp is invalid.")
	if abs(int(time.time()) - stamp) > _timestamp_window():
		_raise_replay("REPLAY_REJECTED", "Signed ingress timestamp is outside the allowed window.")
	provided = provided.strip()
	if provided.startswith("sha256="):
		provided = provided[7:]
	provided_candidates = [provided]
	try:
		provided_candidates.append(base64.b64decode(provided, validate=True).hex())
	except Exception:
		pass
	for version, secret in _source_secret(source_namespace):
		expected = hmac.new(
			secret, signing_message(raw_body, source_namespace, str(timestamp), nonce), hashlib.sha256
		).hexdigest()
		if any(hmac.compare_digest(expected, candidate) for candidate in provided_candidates):
			return version
	_raise_replay("REPLAY_REJECTED", "Signed ingress signature is invalid.")


def _timestamp_window() -> int:
	try:
		configured = frappe.conf.get("student_intake_webhook_timestamp_window")
		if configured:
			return max(1, int(configured))
	except Exception:
		pass
	return TIMESTAMP_WINDOW_SECONDS


def _json_body(raw_body: bytes) -> dict[str, Any]:
	try:
		payload = json.loads(raw_body.decode("utf-8"))
	except (UnicodeDecodeError, ValueError):
		_raise_replay("INVALID_INPUT", "Signed ingress payload is not valid JSON.")
	if not isinstance(payload, dict):
		_raise_replay("INVALID_INPUT", "Signed ingress payload must be a JSON object.")
	return payload


@frappe.whitelist(allow_guest=True, methods=["POST"])
def receive():
	"""Verify and forward one signed source record."""
	raw_body = _raw_body()
	namespace = _header(NAMESPACE_HEADER)
	timestamp = _header(TIMESTAMP_HEADER)
	nonce = _header(NONCE_HEADER)
	signature = _header(SIGNATURE_HEADER)
	verify_signature(raw_body, namespace or "", timestamp or "", nonce or "", signature or "")
	payload = _json_body(raw_body)
	context = _source_context(namespace or "")
	# Header values are authoritative for replay identity.  A body field with the
	# same name is ignored, preventing a provider from signing one record and
	# routing another.
	record_id = _header(RECORD_HEADER) or payload.get("source_record_id") or payload.get("external_id")
	idempotency_key = _header(IDEMPOTENCY_HEADER) or payload.get("idempotency_key")
	correlation_id = _header(CORRELATION_HEADER) or payload.get("correlation_id")
	if not record_id or not idempotency_key:
		_raise_replay("INVALID_INPUT", "Signed ingress source record and idempotency key are required.")
	if "consent" not in payload:
		_raise_replay("INVALID_INPUT", "consent is required for external contact intake.")
	canonical_payload = _normalize_contact_payload(
		{
			**payload,
			"source_namespace": namespace,
			"external_id": record_id,
			"idempotency_key": idempotency_key,
		}
	)
	result = submit_intake(
		canonical_payload,
		source_namespace=namespace,
		source_record_id=str(record_id),
		idempotency_key=str(idempotency_key),
		correlation_id=str(correlation_id) if correlation_id else None,
		nonce=nonce,
		signed_context=context,
		request_payload=payload,
		request_fingerprint=body_fingerprint(raw_body),
	)
	return _intake_response(result)


# Stable aliases used by provider integrations during rollout.
submit_signed_intake = receive
handle = receive
verify_webhook_signature = verify_signature
handle_webhook = receive
