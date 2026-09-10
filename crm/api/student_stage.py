"""HTTP adapter for Student contact-stage transitions."""

from __future__ import annotations

import frappe

from crm.fcrm.student_stage import StudentStageError, set_student_stage
from crm.fcrm.student_reference import canonical_student


def _resolve_student_name(student: str) -> str:
	"""Normalize canonical Student IDs and legacy public references."""
	value = str(student or "").strip()
	return canonical_student(value) or value


@frappe.whitelist(methods=["POST"])
def request_transition(
	student: str,
	target_stage: str,
) -> dict:
	try:
		return set_student_stage(_resolve_student_name(student), target_stage)
	except StudentStageError as exc:
		exception_type = (
			frappe.PermissionError if exc.code in {"FORBIDDEN", "UNAUTHORIZED"} else frappe.ValidationError
		)
		frappe.throw(str(exc), exception_type)
