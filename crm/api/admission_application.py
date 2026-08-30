"""Server-owned application command boundary."""

from __future__ import annotations

import frappe

from crm.fcrm.admission_application import create_application as _create_application


@frappe.whitelist(methods=["POST"])
def create_application(student: str, values, expected_revision: int, idempotency_key: str):
	if isinstance(values, str):
		values = frappe.parse_json(values)
	return _create_application(
		student=student,
		values=values,
		expected_revision=expected_revision,
		idempotency_key=idempotency_key,
	)
