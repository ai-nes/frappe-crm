"""Public boundary for canonical Student Payment event ingestion."""

from __future__ import annotations

import frappe

from crm.fcrm.student_payment import record_payment_event


@frappe.whitelist(methods=["POST"])
def record_event(
	payment: str,
	event_type: str,
	event_at: str,
	source_reference: str,
	amount_delta: float = 0,
	supersedes: str | None = None,
):
	return record_payment_event(
		payment=payment,
		event_type=event_type,
		event_at=event_at,
		source_reference=source_reference,
		amount_delta=float(amount_delta or 0),
		supersedes=supersedes,
	)
