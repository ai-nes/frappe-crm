"""Whitelisted adapter for the Student Detail admissions action boundary."""

from __future__ import annotations

import frappe
from frappe import _

from crm.fcrm.student_admissions import StudentAdmissionsError
from crm.fcrm.student_admissions import perform_action as _perform_action
from crm.fcrm.student_admissions import set_attachment_visibility as _set_attachment_visibility


def _call(callable_, **kwargs):
	try:
		return callable_(**kwargs)
	except StudentAdmissionsError as exc:
		exception_type = frappe.PermissionError if exc.code in {"UNAUTHORIZED", "OUT_OF_SCOPE", "FORBIDDEN"} else frappe.ValidationError
		frappe.throw(_("{0}: {1}").format(exc.code, str(exc)), exception_type)


@frappe.whitelist(methods=["POST"])
def perform_action(student: str, action: str, expected_revision, idempotency_key: str, payload=None, correlation_id=None, occurred_at=None):
	return _call(_perform_action, student=student, action=action, expected_revision=expected_revision, idempotency_key=idempotency_key, payload=payload, correlation_id=correlation_id, occurred_at=occurred_at)


@frappe.whitelist(methods=["POST"])
def set_attachment_visibility(student: str, file_name: str, is_private, confirm_public=False):
	return _call(_set_attachment_visibility, student=student, file_name=file_name, is_private=is_private, confirm_public=confirm_public)
