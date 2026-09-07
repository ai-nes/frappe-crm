"""Commands for verified parent decision context in Student 360."""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.services.student_context import mark_student_context_changed

_DECISION_ROLES = {"Unknown", "Primary decision maker", "Influencer", "Information only"}
_DECISION_INFLUENCE = {"Unknown", "High", "Medium", "Low"}


def _student_for_write(student: str):
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	doc = frappe.get_doc("CRM Lead", student)
	if not doc.has_permission("write"):
		frappe.throw(_("You do not have permission to update this Student's parent context."), frappe.PermissionError)
	return doc


def _ensure_contact_scope(contact: str, actor: str) -> None:
	if not frappe.has_permission("CRM Student", "read", contact, user=actor):
		frappe.throw(_("The parent Contact is outside your permitted scope."), frappe.PermissionError)


def _ensure_authorized_parent_reviewer(contact: str | None = None) -> str:
	"""Require an admissions reviewer and, when supplied, Contact read scope."""
	actor = frappe.session.user
	roles = set(frappe.get_roles(actor))
	if actor != "Administrator" and "System Manager" not in roles and "Admissions Director" not in roles:
		frappe.throw(
			_("Only an authorized admissions reviewer can manage parent authority."),
			frappe.PermissionError,
		)
	if contact:
		_ensure_contact_scope(contact, actor)
	return actor


def record_parent_contact_authority(
	student: str,
	contact: str,
	*,
	relationship_type: str,
	decision_role: str = "Unknown",
	decision_influence: str = "Unknown",
	concerns: str | None = None,
	lawful_basis: str,
	allowed_channels: Any,
	proof_reference: str,
	effective_at=None,
	expires_at=None,
) -> dict[str, Any]:
	student_doc = _student_for_write(student)
	if not frappe.db.exists("CRM Student", contact):
		frappe.throw(_("The parent Contact does not exist."), frappe.ValidationError)
	actor = _ensure_authorized_parent_reviewer(contact)
	linked_student = frappe.db.get_value("CRM Student", contact, "student")
	if linked_student and linked_student != student_doc.name:
		frappe.throw(_("The parent Contact is linked to a different Student."), frappe.ValidationError)
	if decision_role not in _DECISION_ROLES or decision_influence not in _DECISION_INFLUENCE:
		frappe.throw(_("Parent decision context contains an invalid role or influence."), frappe.ValidationError)
	if not str(relationship_type or "").strip() or not str(lawful_basis or "").strip() or not str(proof_reference or "").strip():
		frappe.throw(_("relationship_type, lawful_basis and proof_reference are required."), frappe.ValidationError)
	try:
		channels = json.loads(allowed_channels) if isinstance(allowed_channels, str) else allowed_channels
	except (TypeError, ValueError):
		channels = None
	if not isinstance(channels, list) or not channels or any(not str(channel).strip() for channel in channels):
		frappe.throw(_("At least one allowed parent-contact channel is required."), frappe.ValidationError)
	flags = frappe.flags
	previous = getattr(flags, "student_parent_context_service", False)
	flags.student_parent_context_service = True
	try:
		doc = frappe.get_doc(
			{
				"doctype": "CRM Parent Contact Authority",
				"student": student_doc.name,
				"contact": contact,
				"relationship_verified": 1,
				"relationship_type": str(relationship_type).strip()[:140],
				"decision_role": decision_role,
				"decision_influence": decision_influence,
				"concerns": str(concerns or "").strip()[:2000] or None,
				"lawful_basis": str(lawful_basis).strip()[:140],
				"allowed_channels": json.dumps([str(channel).strip()[:80] for channel in channels], ensure_ascii=False),
				"effective_at": effective_at or now_datetime(),
				"expires_at": expires_at,
				"proof_reference": str(proof_reference).strip()[:500],
			}
		).insert(ignore_permissions=True)
	finally:
		flags.student_parent_context_service = previous
	mark_student_context_changed(student_doc.name, "parent_decision_context_changed")
	return {
		"name": doc.name,
		"student": doc.student,
		"contact": doc.contact,
		"relationship_type": doc.relationship_type,
		"decision_role": doc.decision_role,
		"decision_influence": doc.decision_influence,
		"allowed_channels": channels,
		"effective_at": str(doc.effective_at),
		"expires_at": str(doc.expires_at) if doc.expires_at else None,
	}


def revoke_parent_contact_authority(name: str, *, evidence: str) -> dict[str, Any]:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	actor = _ensure_authorized_parent_reviewer()
	doc = frappe.get_doc("CRM Parent Contact Authority", name)
	student = _student_for_write(doc.student)
	_ensure_contact_scope(doc.contact, actor)
	if doc.revoked_at:
		return {"name": doc.name, "student": doc.student, "revoked_at": str(doc.revoked_at), "status": "already_revoked"}
	if not str(evidence or "").strip():
		frappe.throw(_("Revocation evidence is required."), frappe.ValidationError)
	# Revocation is a command update; the original relationship facts remain immutable.
	doc.revoked_at = now_datetime()
	doc.revocation_evidence = str(evidence).strip()[:2000]
	previous = getattr(frappe.flags, "student_parent_context_service", False)
	frappe.flags.student_parent_context_service = True
	try:
		doc.save(ignore_permissions=True)
	finally:
		frappe.flags.student_parent_context_service = previous
	mark_student_context_changed(student.name, "parent_decision_context_revoked")
	return {"name": doc.name, "student": doc.student, "revoked_at": str(doc.revoked_at), "status": "revoked"}
