"""Scoped Student SLA command adapters with stable error codes."""

from __future__ import annotations

import frappe
from frappe import _

from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_sla import (
	StudentSLAError,
	get_student_sla_status as _get_status,
	pause_sla as _pause,
	process_due_sla_attempts as _process_due,
	approve_sla_reset as _approve_reset,
	record_qualifying_response as _respond,
	request_sla_reset as _request_reset,
	get_sla_reset_report as _reset_report,
	resume_sla as _resume,
)


def _require(capability: str):
	actor = frappe.session.user
	caps = capabilities_for_roles(frappe.get_roles(actor), administrator=actor == "Administrator")
	if capability not in caps:
		frappe.throw(_("You are not permitted to perform this Student SLA action."), frappe.PermissionError)


def _call(callable_, **kwargs):
	try:
		return callable_(**kwargs)
	except StudentSLAError as exc:
		exception_type = frappe.PermissionError if exc.code in {"OUT_OF_SCOPE", "UNAUTHORIZED"} else frappe.ValidationError
		frappe.throw(_("{0}: {1}").format(exc.code, str(exc)), exception_type)


@frappe.whitelist()
def get_student_sla_status(student: str) -> dict:
	_require("student.sla.read")
	return _call(_get_status, student=student)


@frappe.whitelist(methods=["POST"])
def pause_student_sla(attempt: str, reason_code: str, expected_revision: int, idempotency_key: str | None = None) -> dict:
	_require("student.sla.pause")
	return _call(_pause, attempt_name=attempt, reason_code=reason_code, expected_revision=expected_revision)


@frappe.whitelist(methods=["POST"])
def resume_student_sla(attempt: str, expected_revision: int, idempotency_key: str | None = None) -> dict:
	_require("student.sla.pause")
	return _call(_resume, attempt_name=attempt, expected_revision=expected_revision)


@frappe.whitelist(methods=["POST"])
def record_student_response(attempt: str, interaction: str, expected_revision: int, idempotency_key: str | None = None) -> dict:
	_require("student.sla.respond")
	return _call(_respond, attempt_name=attempt, interaction_name=interaction, expected_revision=expected_revision)


@frappe.whitelist(methods=["POST"])
def request_student_sla_reset(attempt: str, reason: str, evidence_reference: str, expected_revision: int) -> dict:
	_require("student.sla.reset.request")
	return _call(
		_request_reset,
		attempt_name=attempt,
		reason=reason,
		evidence_reference=evidence_reference,
		expected_revision=expected_revision,
	)


@frappe.whitelist(methods=["POST"])
def approve_student_sla_reset(attempt: str, expected_revision: int) -> dict:
	_require("student.sla.reset.approve")
	return _call(_approve_reset, attempt_name=attempt, expected_revision=expected_revision)


@frappe.whitelist()
def get_student_sla_reset_report(campus: str | None = None) -> dict:
	_require("student.sla.escalation.read")
	return _call(_reset_report, campus=campus)


def process_due_sla_attempts():
	return _process_due()
