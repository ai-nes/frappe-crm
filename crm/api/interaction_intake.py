"""Public interaction-ingress adapter over the canonical interaction command."""

from __future__ import annotations

import json
from typing import Any

import frappe

from crm.fcrm.interaction_log import (
	ingest_external_interaction as _submit_interaction,
)
from crm.fcrm.interaction_log import (
	normalize_external_interaction_payload,
)


def _request_json(payload: Any = None):
	if payload is not None:
		return payload
	try:
		return frappe.request.get_json(silent=True)
	except Exception:
		return None


def _normalize_interaction_payload(payload: dict[str, Any]) -> dict[str, Any]:
	"""Adapt the PRD shape while preserving the canonical source boundary."""
	if not isinstance(payload, dict):
		return normalize_external_interaction_payload(payload)
	canonical = dict(payload)
	has_explicit_target = bool(
		payload.get("student_id") or payload.get("student") or payload.get("contact_id")
	)
	if not canonical.get("source_namespace") and canonical.get("source_system"):
		canonical["source_namespace"] = canonical["source_system"]
	if not canonical.get("source_record_id") and canonical.get("message_id"):
		canonical["source_record_id"] = canonical["message_id"]
	if has_explicit_target and not canonical.get("source_record_id") and canonical.get("external_id"):
		canonical["source_record_id"] = canonical["external_id"]
	if not has_explicit_target and not canonical.get("target_external_id") and canonical.get("external_id"):
		canonical["target_external_id"] = canonical["external_id"]
	return normalize_external_interaction_payload(canonical)


def _interaction_response(result: dict[str, Any]) -> dict[str, Any]:
	return {
		"interaction_id": result.get("interaction"),
		"student_id": result.get("student"),
		"contact_id": result.get("contact"),
		"status": result.get("outcome"),
		"receipt_id": result.get("receipt"),
	}


@frappe.whitelist(methods=["POST"])
def submit_interaction(payload: dict[str, Any] | str | None = None) -> dict[str, Any]:
	"""Submit one scoped external interaction through the domain command."""
	payload = _request_json(payload)
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except ValueError:
			frappe.throw("Payload must be a valid JSON object.", frappe.ValidationError)
	result = _submit_interaction(_normalize_interaction_payload(payload))
	return _interaction_response(result)


intake_interaction = submit_interaction
receive = submit_interaction
