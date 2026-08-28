"""Whitelisted adapter for the Student ownership command.

The adapter accepts only command inputs.  Actor, policy scope, current
timestamp, and event contents are derived by ``crm.fcrm.student_ownership``.
"""

from __future__ import annotations

import frappe
from frappe import _

from crm.fcrm.student_ownership import (
	StudentOwnershipError,
	change_student_ownership as _change_student_ownership,
	get_eligible_ownership_targets as _get_eligible_ownership_targets,
	get_student_ownership as _get_student_ownership,
)


_PERMISSION_ERRORS = {"UNAUTHORIZED", "OUT_OF_SCOPE"}


def _read_command(callable_, **kwargs):
	try:
		return callable_(**kwargs)
	except StudentOwnershipError as exc:
		exception_type = frappe.PermissionError if exc.code in _PERMISSION_ERRORS else frappe.ValidationError
		frappe.throw(_("{0}: {1}").format(exc.code, str(exc)), exception_type)


@frappe.whitelist()
def get_student_ownership(student: str) -> dict:
	return _read_command(_get_student_ownership, student=student)


@frappe.whitelist()
def get_eligible_ownership_targets(student: str) -> dict:
	return _read_command(_get_eligible_ownership_targets, student=student)


@frappe.whitelist(methods=["POST"])
def change_student_ownership(
	student: str,
	target_kind: str,
	target_id: str,
	target_team_id: str | None = None,
	reason: str | None = None,
	idempotency_key: str | None = None,
	expected_revision: str | int | None = None,
	correlation_id: str | None = None,
) -> dict:
	"""Change one active Student from a pool to an owner, or vice versa."""

	# The Desk payload uses target_team_id for a pool and target_id for an
	# individual owner.  Normalize that presentation shape to the domain
	# command's single target_id before validation; the server still resolves
	# the named pool and its Team authoritatively.
	if target_kind == "pool" and not target_id:
		target_id, target_team_id = target_team_id, None
	try:
		return _change_student_ownership(
			student=student,
			target_kind=target_kind,
			target_id=target_id,
			target_team_id=target_team_id,
			reason=reason,
			idempotency_key=idempotency_key,
			expected_revision=expected_revision,
			correlation_id=correlation_id,
		)
	except StudentOwnershipError as exc:
		exception_type = frappe.PermissionError if exc.code in _PERMISSION_ERRORS else frappe.ValidationError
		# Keep the machine error at the start of the RPC message.  No actor,
		# target-scope details, HMAC input, or sensitive reason is exposed.
		frappe.throw(_("{0}: {1}").format(exc.code, str(exc)), exception_type)
