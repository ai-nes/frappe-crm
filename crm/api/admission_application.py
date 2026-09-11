"""Server-owned application command boundary."""

from __future__ import annotations

import frappe

from crm.fcrm.admission_application import (
	create_application as _create_application,
)
from crm.fcrm.admission_application import (
	update_application as _update_application,
)
from crm.fcrm.admission_application import (
	update_application_preference as _update_application_preference,
)


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


@frappe.whitelist(methods=["POST", "PUT"])
def update_preference(application: str, preference: str):
	return _update_application_preference(application=application, preference=preference)


@frappe.whitelist(methods=["PUT"])
def update_application(application: str, values):
	if isinstance(values, str):
		values = frappe.parse_json(values)
	return _update_application(application=application, values=values)
