"""Privacy-right request command service."""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.doctype.crm_student_privacy_request.crm_student_privacy_request import REQUEST_TYPES
from crm.fcrm.student_contact_conversion import contact_is_linked_to_student
from crm.fcrm.student_reference import canonical_student


def _student_for_write(student: str):
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	canonical = canonical_student(student)
	if not canonical:
		frappe.throw(_("A canonical CRM Student is required for privacy requests."), frappe.ValidationError)
	doc = frappe.get_doc("CRM Student", canonical)
	if not doc.has_permission("write"):
		frappe.throw(
			_("You do not have permission to manage privacy requests for this Student."),
			frappe.PermissionError,
		)
	roles = set(frappe.get_roles(frappe.session.user))
	if (
		frappe.session.user != "Administrator"
		and "System Manager" not in roles
		and "Admissions Director" not in roles
	):
		frappe.throw(
			_("Only an authorized privacy reviewer can manage privacy requests."), frappe.PermissionError
		)
	return doc


def open_privacy_request(
	student: str, request_type: str, *, details: str | None = None, contact: str | None = None
) -> dict[str, Any]:
	student = _student_for_write(student).name
	request_type = str(request_type or "").strip()
	if request_type not in REQUEST_TYPES:
		frappe.throw(_("Privacy request type is invalid."), frappe.ValidationError)
	if contact:
		if not frappe.db.exists("CRM Student", contact):
			frappe.throw(_("The privacy-request Contact does not exist."), frappe.ValidationError)
		if not contact_is_linked_to_student(contact, student) and not frappe.db.exists(
			"CRM Parent Contact Authority", {"student": student, "contact": contact}
		):
			frappe.throw(
				_("The privacy-request Contact is not related to this Student."), frappe.ValidationError
			)
	doc = frappe.get_doc(
		{
			"doctype": "CRM Student Privacy Request",
			"student": student,
			"contact": contact,
			"request_type": request_type,
			"status": "open",
			"requested_at": now_datetime(),
			"requested_by": frappe.session.user,
			"details": str(details or "").strip()[:2000] or None,
			"evidence_reference": f"privacy-request:{student}:{request_type}:{frappe.generate_hash(length=16)}",
		}
	)
	doc.flags.student_privacy_command = True
	doc.insert(ignore_permissions=True)
	from crm.services.student_context import mark_student_context_changed

	mark_student_context_changed(student, "privacy_request_opened")
	return serialize_request(doc)


def resolve_privacy_request(
	name: str, status: str, resolution: str, *, evidence_reference: str | None = None
) -> dict[str, Any]:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	doc = frappe.get_doc("CRM Student Privacy Request", name)
	_student_for_write(doc.student)
	if status not in {"in_progress", "completed", "rejected"}:
		frappe.throw(_("Privacy request status is invalid."), frappe.ValidationError)
	if doc.status in {"completed", "rejected"}:
		frappe.throw(_("A completed or rejected privacy request is immutable."), frappe.PermissionError)
	if status == "in_progress" and doc.status != "open":
		frappe.throw(_("An in-progress privacy request cannot be moved backwards."), frappe.ValidationError)
	if status == "completed" and not str(resolution or "").strip():
		frappe.throw(_("A completed privacy request requires resolution evidence."), frappe.ValidationError)
	doc.status = status
	if status == "in_progress":
		# In-progress is a workflow state, not a resolution event.
		doc.resolution = None
		doc.resolved_by = None
		doc.resolved_at = None
	else:
		doc.resolution = str(resolution or "").strip()[:2000]
		doc.evidence_reference = str(evidence_reference or doc.evidence_reference or "")[:256]
		doc.resolved_by = frappe.session.user
		doc.resolved_at = now_datetime()
	doc.flags.student_privacy_command = True
	doc.save(ignore_permissions=True)
	from crm.services.student_context import mark_student_context_changed

	mark_student_context_changed(doc.student, "privacy_request_resolved")
	return serialize_request(doc)


def serialize_request(doc) -> dict[str, Any]:
	return {
		"name": doc.name,
		"student": doc.student,
		"contact": doc.contact,
		"request_type": doc.request_type,
		"status": doc.status,
		"requested_at": str(doc.requested_at) if doc.requested_at else None,
		"requested_by": doc.requested_by,
		"details": doc.details,
		"resolved_at": str(doc.resolved_at) if doc.resolved_at else None,
		"resolved_by": doc.resolved_by,
		"resolution": doc.resolution,
		"evidence_reference": doc.evidence_reference,
	}
