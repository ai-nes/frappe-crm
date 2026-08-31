"""Authoritative append-only writer for Student Payment events."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import frappe
from frappe import _

from crm.fcrm.admissions_migration import stable_fingerprint


@contextmanager
def _payment_event_writer_context():
	previous = getattr(frappe.flags, "payment_event_writer", False)
	frappe.flags.payment_event_writer = True
	try:
		yield
	finally:
		frappe.flags.payment_event_writer = previous


def record_payment_event(
	*,
	payment: str,
	event_type: str,
	event_at: str,
	amount_delta: float = 0,
	source_reference: str,
	supersedes: str | None = None,
) -> dict[str, Any]:
	"""Record one payment status/refund/correction event, replaying retries."""

	if not all(str(value or "").strip() for value in (payment, event_type, event_at, source_reference)):
		frappe.throw(
			_("Payment, event type, event time and source reference are required."), frappe.ValidationError
		)
	payment_row = frappe.db.get_value("CRM Student Payment", payment, ["currency"], as_dict=True)
	if not payment_row:
		frappe.throw(_("Source Payment does not exist."), frappe.DoesNotExistError)
	fingerprint = stable_fingerprint(
		"payment-event",
		payment,
		event_type,
		event_at,
		amount_delta,
		payment_row.currency,
		source_reference,
		supersedes,
	)
	existing = frappe.db.get_value(
		"CRM Student Payment Event",
		{"idempotency_fingerprint": fingerprint},
		["name", "event_key"],
		as_dict=True,
	)
	if existing:
		return {"event": existing.name, "event_key": existing.event_key, "replayed": True}

	values = {
		"doctype": "CRM Student Payment Event",
		"payment": payment,
		"event_type": event_type,
		"event_at": event_at,
		"amount_delta": amount_delta,
		"currency": payment_row.currency,
		"supersedes": supersedes,
		"source_reference": source_reference,
		"idempotency_fingerprint": fingerprint,
	}
	with _payment_event_writer_context():
		doc = frappe.get_doc(values).insert(ignore_permissions=True)
	if event_type in {"Pending", "Received", "Failed", "Refunded"}:
		frappe.db.set_value(
			"CRM Student Payment",
			payment,
			"status",
			event_type,
			update_modified=False,
		)
	return {"event": doc.name, "event_key": doc.event_key, "replayed": False}
