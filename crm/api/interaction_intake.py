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
	read_interaction_evidence,
)


def _request_json(payload: Any = None):
	if payload is not None:
		return payload
	try:
		return frappe.request.get_json(silent=True)
	except Exception:
		return None


def _normalize_interaction_payload(payload: dict[str, Any]) -> dict[str, Any]:
	"""Validate the canonical interaction ingress shape without legacy aliases."""
	return normalize_external_interaction_payload(payload)


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


@frappe.whitelist(methods=["POST"])
def get_interaction_evidence(interaction: str, expected_revision: int, expected_digest: str) -> dict:
	"""Explicit service capability for one revision's raw turns; never a user-facing API."""
	return read_interaction_evidence(
		interaction, expected_revision=int(expected_revision), expected_digest=expected_digest
	)


@frappe.whitelist(methods=["POST"])
def claim_interaction_analysis_run(run_id: str, stage_generation: int) -> dict:
	from crm.fcrm.interaction_analysis import claim_interaction_analysis_run as claim

	return claim(run_id=run_id, stage_generation=int(stage_generation))


@frappe.whitelist(methods=["POST"])
def settle_interaction_analysis_result(
	run_id: str,
	stage_generation: int,
	lease_token: str,
	expected_source_revision: int,
	expected_source_digest: str,
	state: str,
	policy_revision: str,
	model_revision: str,
	result_digest: str,
	intent=None,
	terminal_reason: str | None = None,
) -> dict:
	"""Service-only, fenced settlement for the canonical Interaction worker."""
	from crm.fcrm.interaction_analysis import settle_interaction_analysis_result as settle

	if isinstance(intent, str):
		intent = frappe.parse_json(intent)
	return settle(
		run_id=run_id,
		stage_generation=int(stage_generation),
		lease_token=lease_token,
		expected_source_revision=int(expected_source_revision),
		expected_source_digest=expected_source_digest,
		state=state,
		policy_revision=policy_revision,
		model_revision=model_revision,
		result_digest=result_digest,
		intent=intent,
		terminal_reason=terminal_reason,
	)
