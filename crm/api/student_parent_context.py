"""Whitelisted Student 360 parent decision-context commands."""

from __future__ import annotations

import json

import frappe

from crm.fcrm.student_parent_context import record_parent_contact_authority as _record, revoke_parent_contact_authority as _revoke


@frappe.whitelist(methods=["POST"])
def record_parent_authority(
	student: str,
	contact: str,
	relationship_type: str,
	decision_role: str = "Unknown",
	decision_influence: str = "Unknown",
	concerns: str | None = None,
	lawful_basis: str | None = None,
	allowed_channels=None,
	proof_reference: str | None = None,
	effective_at=None,
	expires_at=None,
) -> dict:
	if isinstance(allowed_channels, str):
		try:
			allowed_channels = json.loads(allowed_channels)
		except (TypeError, ValueError):
			allowed_channels = None
	return _record(
		student,
		contact,
		relationship_type=relationship_type,
		decision_role=decision_role,
		decision_influence=decision_influence,
		concerns=concerns,
		lawful_basis=lawful_basis or "",
		allowed_channels=allowed_channels,
		proof_reference=proof_reference or "",
		effective_at=effective_at,
		expires_at=expires_at,
	)


@frappe.whitelist(methods=["POST"])
def revoke_parent_authority(name: str, evidence: str) -> dict:
	return _revoke(name, evidence=evidence)
