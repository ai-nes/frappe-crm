"""HTTP adapter for the authoritative Student conversion command."""

from __future__ import annotations

import frappe

from crm.fcrm.student_conversion import (
	StudentConversionError,
)
from crm.fcrm.student_conversion import (
	convert_student as _convert_student,
)

_PERMISSION_ERRORS = {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE"}


@frappe.whitelist(methods=["POST"])
def convert_student(
	student: str,
	expected_lifecycle_revision: str | int,
	idempotency_key: str,
	correlation_id: str | None = None,
	target_student: str | None = None,
) -> dict:
	"""Convert a qualified CRM Lead into the canonical CRM Student snapshot.

	``student`` is retained as the request key for compatibility. New clients
	may pass ``target_student`` to use an independently created/imported Student.
	"""
	try:
		command = dict(
			student=student,
			expected_lifecycle_revision=expected_lifecycle_revision,
			idempotency_key=idempotency_key,
			correlation_id=correlation_id,
		)
		if target_student:
			command["target_student"] = target_student
		return _convert_student(**command)
	except StudentConversionError as exc:
		exception_type = frappe.PermissionError if exc.code in _PERMISSION_ERRORS else frappe.ValidationError
		frappe.throw(str(exc), exception_type)


@frappe.whitelist(methods=["POST"])
def convert_lead(
	lead: str,
	expected_lifecycle_revision: str | int,
	idempotency_key: str,
	correlation_id: str | None = None,
	target_student: str | None = None,
) -> dict:
	"""Clear-named Lead -> Student alias for new clients."""
	return convert_student(
		student=lead,
		expected_lifecycle_revision=expected_lifecycle_revision,
		idempotency_key=idempotency_key,
		correlation_id=correlation_id,
		target_student=target_student,
	)
