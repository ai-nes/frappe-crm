"""Internal identity helpers for CRM Leads."""

from __future__ import annotations

import frappe


def resolve_lead_name(value: str | None) -> str:
	"""Resolve a public Lead ID to the Frappe document name."""
	lead_value = str(value or "").strip()
	if not lead_value or frappe.db.exists("CRM Lead", lead_value):
		return lead_value
	meta = frappe.get_meta("CRM Lead")
	if any(getattr(field, "fieldname", None) == "lead_id" for field in meta.fields):
		return frappe.db.get_value("CRM Lead", {"lead_id": lead_value}, "name") or lead_value
	return lead_value
