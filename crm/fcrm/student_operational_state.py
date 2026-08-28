"""Guards for service-owned Phase 4 state projections."""

import frappe
from frappe.utils import now_datetime


def require_service_flag(flag: str) -> None:
	if not getattr(frappe.flags, flag, False):
		frappe.throw("This operational record can only be changed by its service.")


def validate_state_transition(doc, flag: str, transitions: dict[str, set[str]]) -> None:
	require_service_flag(flag)
	if doc.is_new():
		return
	previous = doc.get_doc_before_save()
	if not previous:
		return
	# Every service mutation is compare-and-swap fenced.  The service must load
	# the current row, increment revision exactly once, and preserve a lease
	# token while completing a leased item.
	current_revision = doc.get("revision")
	previous_revision = previous.get("revision")
	if current_revision is not None and previous_revision is not None:
		try:
			if int(current_revision) != int(previous_revision) + 1:
				frappe.throw("Operational state revision conflict; reload before retrying.")
		except (TypeError, ValueError):
			frappe.throw("Operational state revision must be an integer.")
	if previous.get("status") == "leased" and doc.get("lease_token") != previous.get("lease_token"):
		expired = previous.get("lease_expires_at") and previous.get("lease_expires_at") <= now_datetime()
		if not (expired and doc.get("status") == "pending"):
			frappe.throw("A leased operational item requires its original lease token.")
	if previous.get("status") != "leased" and doc.get("status") == "leased":
		if not doc.get("lease_token") or not doc.get("lease_expires_at"):
			frappe.throw("A leased operational item requires a lease token and expiry.")
		if doc.get("lease_expires_at") <= now_datetime():
			frappe.throw("A leased operational item requires a future expiry.")
	if previous.status == doc.status:
		return
	allowed = transitions.get(previous.status, set())
	if doc.status not in allowed:
		frappe.throw(f"Invalid {doc.doctype} state transition: {previous.status} → {doc.status}")
