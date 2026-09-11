"""HTTP adapters for the Lead processing workflow."""

from __future__ import annotations

import frappe

from crm.api.assignment_workspace import _actor_context
from crm.fcrm.lead_identity import resolve_lead_name
from crm.fcrm.lead_processing import (
	LeadProcessingError,
)
from crm.fcrm.lead_processing import (
	assign_lead as _assign_lead,
)
from crm.fcrm.lead_processing import (
	handoff_lead as _handoff_lead,
)
from crm.fcrm.lead_processing import (
	list_lead_assignment_targets as _list_lead_assignment_targets,
)
from crm.fcrm.lead_processing import (
	preview_lead as _preview_lead,
)
from crm.fcrm.lead_processing import (
	process_lead as _process_lead,
)
from crm.fcrm.lead_processing import (
	process_new_leads as _process_new_leads,
)
from crm.fcrm.lead_processing import (
	reopen_lead as _reopen_lead,
)
from crm.fcrm.lead_processing import (
	update_processing_status as _update_processing_status,
)
from crm.fcrm.student_conversion import StudentConversionError

_PERMISSION_ERRORS = {"FORBIDDEN", "UNAUTHORIZED", "OUT_OF_SCOPE"}


def _run(command, **kwargs):
	try:
		return command(**kwargs)
	except (LeadProcessingError, StudentConversionError) as exc:
		exception_type = frappe.PermissionError if exc.code in _PERMISSION_ERRORS else frappe.ValidationError
		frappe.throw(str(exc), exception_type)


def _require_assignment_access():
	"""Require the server-side capability for manual Lead assignment."""
	return _actor_context(required_capabilities={"student.routing.operate"})


@frappe.whitelist(methods=["POST"])
def process_lead(lead: str, resolution: str | None = None, reason: str | None = None) -> dict:
	return _run(_process_lead, lead=resolve_lead_name(lead), resolution=resolution, reason=reason)


@frappe.whitelist(methods=["POST"])
def process_new_leads(admission_year: str | int | None = None, limit: str | int | None = None) -> dict:
	return _run(_process_new_leads, admission_year=admission_year, limit=limit)


@frappe.whitelist(methods=["POST"])
def update_processing_status(lead: str, status: str, reason: str | None = None) -> dict:
	return _run(_update_processing_status, lead=resolve_lead_name(lead), status=status, reason=reason)


@frappe.whitelist(methods=["POST"])
def reopen_lead(lead: str, reason: str | None = None) -> dict:
	return _run(_reopen_lead, lead=resolve_lead_name(lead), reason=reason)


@frappe.whitelist(methods=["GET", "POST"])
def preview_lead(lead: str) -> dict:
	return _run(_preview_lead, lead=resolve_lead_name(lead))


@frappe.whitelist(methods=["POST"])
def assign_lead(
	lead: str,
	owner_staff: str,
	target_team_id: str,
	reason: str,
	idempotency_key: str,
	expected_revision: str | int,
	correlation_id: str | None = None,
) -> dict:
	_require_assignment_access()
	return _run(
		_assign_lead,
		lead=resolve_lead_name(lead),
		owner_staff=owner_staff,
		target_team_id=target_team_id,
		reason=reason,
		idempotency_key=idempotency_key,
		expected_revision=expected_revision,
		correlation_id=correlation_id,
	)


@frappe.whitelist(methods=["POST"])
def handoff_lead(
	lead: str,
	idempotency_key: str,
	expected_lifecycle_revision: str | int | None = None,
	correlation_id: str | None = None,
	target_student: str | None = None,
) -> dict:
	return _run(
		_handoff_lead,
		lead=lead,
		expected_lifecycle_revision=expected_lifecycle_revision,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
		target_student=target_student,
	)


@frappe.whitelist(methods=["GET"])
def list_lead_assignment_targets(lead: str) -> dict:
	"""List Sale/CTV recipients eligible for manual assignment of a Lead."""
	_require_assignment_access()
	return _run(
		_list_lead_assignment_targets,
		lead=resolve_lead_name(lead),
	)


@frappe.whitelist(methods=["POST"])
def convert_to_student(
	lead: str,
	idempotency_key: str | None = None,
	correlation_id: str | None = None,
) -> dict:
	"""Create a new CRM Student from one assigned Lead."""
	lead_name = resolve_lead_name(lead)
	request_key = (
		str(idempotency_key or "").strip()
		or f"lead-convert:{lead_name}:{frappe.generate_hash(length=20)}"
	)
	return _run(
		_handoff_lead,
		lead=lead_name,
		idempotency_key=request_key,
		correlation_id=correlation_id,
		_force_create=True,
	)
