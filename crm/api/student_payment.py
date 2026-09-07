"""Public boundary for canonical Student Payment event ingestion."""

from __future__ import annotations

import frappe

from crm.fcrm.student_payment import record_payment_event


def _require_payment_writer():
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		frappe.throw("Authentication is required.", frappe.PermissionError)
	roles = set(frappe.get_roles(actor))
	service_user = getattr(frappe, "conf", {}).get("crm_student_payment_service_user")
	if (
		actor == "Administrator"
		or "System Manager" in roles
		or "Admissions Director" in roles
		or (service_user and actor == service_user)
	):
		return
	frappe.throw(
		"Only the payment service, System Manager or Admissions Director may record payment events.",
		frappe.PermissionError,
	)


@frappe.whitelist(methods=["POST"])
def record_event(
	payment: str,
	event_type: str,
	event_at: str,
	source_reference: str,
	amount_delta: float = 0,
	supersedes: str | None = None,
):
	_require_payment_writer()
	return record_payment_event(
		payment=payment,
		event_type=event_type,
		event_at=event_at,
		source_reference=source_reference,
		amount_delta=float(amount_delta or 0),
		supersedes=supersedes,
	)
