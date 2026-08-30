"""Public command boundary for Admission Offering approval."""

import frappe

from crm.fcrm.admission_offering import approve_offering


@frappe.whitelist()
def approve(offering: str, idempotency_key: str):
	return approve_offering(offering=offering, idempotency_key=idempotency_key)
