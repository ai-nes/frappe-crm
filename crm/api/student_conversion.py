"""HTTP adapter for the authoritative Student conversion command."""

from __future__ import annotations

import frappe

from crm.fcrm.student_conversion import (
	StudentConversionError,
	convert_student as _convert_student,
)


_PERMISSION_ERRORS = {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE"}


@frappe.whitelist(methods=["POST"])
def convert_student(
	student: str,
	expected_lifecycle_revision: str | int,
	idempotency_key: str,
	correlation_id: str | None = None,
) -> dict:
	"""Convert an Enrolled Student; all target fields are server-derived."""
	try:
		return _convert_student(
			student=student,
			expected_lifecycle_revision=expected_lifecycle_revision,
			idempotency_key=idempotency_key,
			correlation_id=correlation_id,
		)
	except StudentConversionError as exc:
		exception_type = frappe.PermissionError if exc.code in _PERMISSION_ERRORS else frappe.ValidationError
		frappe.throw(str(exc), exception_type)
