"""HTTP adapter for Student contact-stage transitions."""

from __future__ import annotations

import frappe

from crm.fcrm.student_stage import StudentStageError, set_student_stage


@frappe.whitelist(methods=["POST"])
def request_transition(
	student: str,
	target_stage: str,
) -> dict:
	try:
		return set_student_stage(student, target_stage)
	except StudentStageError as exc:
		exception_type = (
			frappe.PermissionError if exc.code in {"FORBIDDEN", "UNAUTHORIZED"} else frappe.ValidationError
		)
		frappe.throw(str(exc), exception_type)
