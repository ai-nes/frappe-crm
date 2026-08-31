"""Approval command for the canonical Admission Offering catalog."""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe import _

from crm.fcrm.admissions_migration import stable_fingerprint


@contextmanager
def _offering_approval_context():
	previous = getattr(frappe.flags, "offering_approval_writer", False)
	frappe.flags.offering_approval_writer = True
	try:
		yield
	finally:
		frappe.flags.offering_approval_writer = previous


def approve_offering(*, offering: str, idempotency_key: str) -> dict[str, str | bool]:
	if not idempotency_key:
		frappe.throw(_("Idempotency Key is required."), frappe.ValidationError)
	if not (
		{"Administrator", "System Manager", "Admissions Director"}
		& set(frappe.get_roles(frappe.session.user))
	):
		frappe.throw(_("Only an Admissions Director can activate an offering."), frappe.PermissionError)
	fingerprint = stable_fingerprint("offering-approval", offering, idempotency_key)
	doc = frappe.get_doc("CRM Admission Offering", offering)
	if doc.status == "Active" and doc.idempotency_fingerprint == fingerprint:
		return {"offering": doc.name, "status": doc.status, "replayed": True}
	if doc.status == "Active":
		frappe.throw(
			_("The offering is already active; a second approval is not allowed."),
			frappe.DuplicateEntryError,
		)
	if doc.status in {"Closed", "Retired"}:
		frappe.throw(_("A closed or retired offering cannot be activated."), frappe.ValidationError)
	doc.status = "Active"
	doc.approved_by = frappe.session.user
	doc.approved_at = frappe.utils.now_datetime()
	doc.source_reference = f"offering-approval:{idempotency_key}"
	doc.idempotency_fingerprint = fingerprint
	with _offering_approval_context():
		doc.save(ignore_permissions=True)
	return {"offering": doc.name, "status": doc.status, "replayed": False}
