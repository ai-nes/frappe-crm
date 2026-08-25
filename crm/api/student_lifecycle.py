"""Thin HTTP adapters for authoritative Student lifecycle commands."""

from __future__ import annotations

import frappe

from crm.fcrm.student_lifecycle import (
	StudentLifecycleError,
)
from crm.fcrm.student_lifecycle import (
	get_lifecycle_context as _get_lifecycle_context,
)
from crm.fcrm.student_lifecycle import (
	reopen as _reopen,
)
from crm.fcrm.student_lifecycle import (
	request_transition as _request_transition,
)


def _read(callable_, **kwargs):
	try:
		return callable_(**kwargs)
	except StudentLifecycleError as exc:
		exc_type = frappe.PermissionError if exc.code in {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE", "DISABLED"} else frappe.ValidationError
		frappe.throw(str(exc), exc_type)


@frappe.whitelist(methods=["POST"])
def request_transition(**kwargs):
	return _read(_request_transition, **kwargs)


@frappe.whitelist(methods=["POST"])
def transition_student_lifecycle(**kwargs):
	return request_transition(**kwargs)


@frappe.whitelist(methods=["POST"])
def reopen_student(student: str, reason: str, expected_revision=None, idempotency_key=None, correlation_id=None):
	return _read(_reopen, student=student, reason=reason, expected_revision=expected_revision, idempotency_key=idempotency_key, correlation_id=correlation_id)


@frappe.whitelist(methods=["POST"])
def reopen(student: str, reason: str, expected_revision=None, idempotency_key=None, correlation_id=None):
	return reopen_student(student=student, reason=reason, expected_revision=expected_revision, idempotency_key=idempotency_key, correlation_id=correlation_id)


@frappe.whitelist()
def get_lifecycle_context(student: str):
	return _read(_get_lifecycle_context, student=student)
