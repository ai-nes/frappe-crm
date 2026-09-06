"""Whitelisted adapter for the Student ownership command.

The adapter accepts only command inputs.  Actor, policy scope, current
timestamp, and event contents are derived by ``crm.fcrm.student_ownership``.
"""

from __future__ import annotations

import unicodedata
import uuid

import frappe
from frappe import _

from crm.fcrm.role_policy import STUDENT_OWNER_PROFILES
from crm.fcrm.student_ownership import (
	StudentOwnershipError,
)
from crm.fcrm.student_ownership import (
	change_student_ownership as _change_student_ownership,
)
from crm.fcrm.student_ownership import (
	get_eligible_ownership_targets as _get_eligible_ownership_targets,
)
from crm.fcrm.student_ownership import (
	get_student_ownership as _get_student_ownership,
)

_PERMISSION_ERRORS = {"UNAUTHORIZED", "OUT_OF_SCOPE"}
_ASSIGNABLE_SALES_SEARCH_FIELDS = ("name", "label", "profile", "role", "function", "team", "campus")


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


@frappe.whitelist(methods=["GET"])
def get_assignable_sales(studentId: str | None = None, search: str | None = None) -> dict:
	"""Return active Sale and CTV Sale staff that can own one Student."""
	student_id = studentId.strip() if isinstance(studentId, str) else studentId
	search_text = search.strip() if isinstance(search, str) else ""
	if len(search_text) > 140:
		frappe.throw(_("search is too long."), frappe.ValidationError)
	result = _read_command(_get_eligible_ownership_targets, student=student_id)
	needle = _search_key(search_text)
	owners = [
		owner
		for owner in result.get("owners", [])
		if owner.get("profile") in STUDENT_OWNER_PROFILES
		if not needle
		or any(needle in _search_key(owner.get(field)) for field in _ASSIGNABLE_SALES_SEARCH_FIELDS)
	]
	return {
		"studentId": student_id,
		"sales": owners,
	}


def _search_key(value) -> str:
	"""Normalize case and accents so Vietnamese names are easy to search."""
	return "".join(
		character
		for character in unicodedata.normalize("NFKD", str(value or "")).casefold()
		if not unicodedata.combining(character)
	)


def _write_command(**kwargs):
	try:
		return _change_student_ownership(**kwargs)
	except StudentOwnershipError as exc:
		exception_type = frappe.PermissionError if exc.code in _PERMISSION_ERRORS else frappe.ValidationError
		# Keep the machine error at the start of the RPC message. No actor,
		# target-scope details, HMAC input, or sensitive reason is exposed.
		frappe.throw(_("{0}: {1}").format(exc.code, str(exc)), exception_type)


@frappe.whitelist(methods=["POST"])
def assign_student_to_sales(
	studentId: str | None = None,
	ownerId: str | None = None,
	targetTeamId: str | None = None,
	reason: str | None = None,
	idempotencyKey: str | None = None,
	expectedRevision: str | int | None = None,
	correlationId: str | None = None,
) -> dict:
	"""Assign or reassign one Student to an eligible Sale or CTV Sale."""
	student_id = studentId.strip() if isinstance(studentId, str) else studentId
	owner_id = ownerId.strip() if isinstance(ownerId, str) else ownerId
	if not student_id or not owner_id:
		frappe.throw(_("studentId and ownerId are required."), frappe.ValidationError)

	# Resolve the target from the same scoped candidate list exposed by the GET
	# endpoint. The ownership command below repeats all checks after locking the
	# Student, so this lookup is only friendly validation and team resolution.
	targets = _read_command(_get_eligible_ownership_targets, student=student_id)
	target = next(
		(item for item in targets.get("owners", []) if str(item.get("name") or item.get("id")) == owner_id),
		None,
	)
	if not target:
		frappe.throw(
			_("ownerId must be an eligible Sale or CTV Sale for this Student."),
			frappe.ValidationError,
		)

	team_id = targetTeamId.strip() if isinstance(targetTeamId, str) else targetTeamId
	if team_id and team_id != target.get("team"):
		frappe.throw(_("targetTeamId does not match the owner's eligible Team."), frappe.ValidationError)
	team_id = team_id or target.get("team")
	if not team_id:
		frappe.throw(_("The owner has no eligible Sales Team for this Student."), frappe.ValidationError)

	ownership = _read_command(_get_student_ownership, student=student_id)
	revision = expectedRevision if expectedRevision not in (None, "") else ownership.get("revision")
	command_id = idempotencyKey.strip() if isinstance(idempotencyKey, str) else idempotencyKey
	command_id = command_id or f"manual-student-assignment:{uuid.uuid4().hex}"
	correlation = correlationId.strip() if isinstance(correlationId, str) else correlationId
	correlation = correlation or f"manual-student-assignment:{uuid.uuid4().hex}"
	manual_reason = reason.strip() if isinstance(reason, str) else reason
	manual_reason = manual_reason or "Manual assignment to Sale or CTV Sale."

	return _write_command(
		student=student_id,
		target_kind="owner",
		target_id=owner_id,
		target_team_id=team_id,
		reason=manual_reason,
		idempotency_key=command_id,
		expected_revision=revision,
		correlation_id=correlation,
	)


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
	return _write_command(
		student=student,
		target_kind=target_kind,
		target_id=target_id,
		target_team_id=target_team_id,
		reason=reason,
		idempotency_key=idempotency_key,
		expected_revision=expected_revision,
		correlation_id=correlation_id,
	)
