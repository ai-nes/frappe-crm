"""Canonical Student intake command gateway.

Only this module is exposed to Desk/REST callers.  Actor, profile and scope are
resolved by :mod:`crm.fcrm.student_intake`; request fields never carry an
authority grant.
"""

from __future__ import annotations

import json
from typing import Any

import frappe

from crm.fcrm.student_intake import decide_intake_review as _decide_intake_review
from crm.fcrm.student_intake import submit_intake as _submit_intake


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
	if isinstance(payload, str):
		try:
			payload = json.loads(payload)
		except ValueError:
			# The command service returns the stable INVALID_INPUT error.
			pass
	return _submit_intake(
		payload,
		source_namespace=source_namespace,
		source_record_id=source_record_id,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
		expected_review_id=expected_review_id,
	)


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
