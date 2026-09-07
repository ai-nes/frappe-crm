"""HTTP adapter for Student contact-stage transitions."""

from __future__ import annotations

import frappe

from crm.fcrm.student_stage import StudentStageError, set_student_stage


def _resolve_student_name(student: str) -> str:
	"""Normalize canonical Student IDs and Lead-backed dashboard IDs."""
	value = str(student or "").strip()
	if not value or frappe.db.exists("CRM Student", value):
		return value
	return frappe.db.get_value("CRM Lead", value, "student") or value


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
