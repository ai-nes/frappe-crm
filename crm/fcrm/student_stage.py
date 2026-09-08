"""Command boundary for the Student contact-stage funnel."""

from __future__ import annotations

from typing import Any

import frappe

STUDENT_STAGES = ("New", "Attempting", "Connected", "Qualified", "Disqualified")
TERMINAL_STAGES = frozenset({"Qualified", "Disqualified"})
SERVICE_FLAG = "student_stage_service"

_NEXT_STAGES = {
	"New": frozenset({"Attempting"}),
	"Attempting": frozenset({"Connected"}),
	"Connected": frozenset({"Qualified", "Disqualified"}),
	"Qualified": frozenset(),
	"Disqualified": frozenset(),
}


class StudentStageError(frappe.ValidationError):
	"""Stable error returned by the Student stage command."""

	def __init__(self, code: str, message: str):
		self.code = code
		self.error_code = code
		super().__init__(message)


def _fail(code: str, message: str):
	raise StudentStageError(code, message)


def validate_stage(stage: Any, *, label: str = "student_stage") -> str:
	value = str(stage or "").strip()
	if value not in STUDENT_STAGES:
		_fail("INVALID_STAGE", f"{label} must be one of: {', '.join(STUDENT_STAGES)}.")
	return value


def validate_transition(current: Any, target: Any) -> tuple[str, str]:
	current_stage = validate_stage(current or "New", label="current_stage")
	target_stage = validate_stage(target, label="target_stage")
	if current_stage == target_stage:
		return current_stage, target_stage
	if target_stage not in _NEXT_STAGES[current_stage]:
		_fail(
			"INVALID_TRANSITION",
			f"Student stage cannot move from {current_stage} to {target_stage}.",
		)
	return current_stage, target_stage


def _load_student(student: str):
	if not isinstance(student, str) or not student.strip():
		_fail("INVALID_INPUT", "student is required.")
	try:
		return frappe.get_doc("CRM Student", student.strip())
	except Exception as exc:
		if exc.__class__.__name__ in {"DoesNotExistError", "ValidationError"}:
			_fail("NOT_FOUND", "Student does not exist.")
		raise


def _lock_student(name: str) -> None:
	frappe.db.sql("select name from `tabCRM Student` where name=%s for update", (name,))


def set_student_stage(
	student: str,
	target_stage: str,
	*,
	_internal_service: bool = False,
) -> dict[str, Any]:
	"""Advance one Student through the contact-stage funnel."""
	doc = _load_student(student)
	_lock_student(doc.name)
	doc = _load_student(doc.name)
	if not _internal_service and not doc.has_permission("write"):
		_fail("FORBIDDEN", "You cannot change this Student stage.")

	raw_current_stage = doc.get("student_stage")
	current_stage, target_stage = validate_transition(raw_current_stage or "New", target_stage)

	if raw_current_stage != target_stage:
		previous = getattr(frappe.flags, SERVICE_FLAG, False)
		setattr(frappe.flags, SERVICE_FLAG, True)
		try:
			frappe.db.set_value(
				"CRM Student",
				doc.name,
				"student_stage",
				target_stage,
				update_modified=True,
			)
		finally:
			setattr(frappe.flags, SERVICE_FLAG, previous)
		from crm.services.student_context import bump_student_context_revision
		from crm.fcrm.nba_evaluations import mark_student_nba_dirty

		change = bump_student_context_revision(
			doc.name,
			"student_stage_change",
			event_id=f"student-stage:{doc.name}:{current_stage}:{target_stage}",
		)
		mark_student_nba_dirty(doc.name)
	else:
		change = None

	return {
		"status": "unchanged" if raw_current_stage == target_stage else "applied",
		"student": doc.name,
		"previous_stage": current_stage,
		"student_stage": target_stage,
		"replayed": raw_current_stage == target_stage,
		"context_revision": change["revision"] if change else None,
	}
