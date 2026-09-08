"""HTTP adapters for the Lead processing workflow."""

from __future__ import annotations

import frappe

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
	preview_lead as _preview_lead,
)
from crm.fcrm.lead_processing import (
	process_lead as _process_lead,
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


@frappe.whitelist(methods=["POST"])
def process_lead(lead: str, resolution: str | None = None, reason: str | None = None) -> dict:
	return _run(_process_lead, lead=lead, resolution=resolution, reason=reason)


@frappe.whitelist(methods=["POST"])
def update_processing_status(lead: str, status: str, reason: str | None = None) -> dict:
	return _run(_update_processing_status, lead=lead, status=status, reason=reason)


@frappe.whitelist(methods=["GET", "POST"])
def preview_lead(lead: str) -> dict:
	return _run(_preview_lead, lead=lead)


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
	return _run(
		_assign_lead,
		lead=lead,
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
