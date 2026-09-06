"""Guarded operational removal for the first unused DocType cleanup wave."""

from __future__ import annotations

import frappe


TARGET_DOCTYPES = (
	"CRM Admissions Migration Run",
	"CRM Campaign Assignment Crosswalk",
	"CRM Fee Policy",
	"CRM Metric Definition",
	"CRM School Migration Quarantine",
	"CRM School Stakeholder Crosswalk",
	"CRM Student Fee Award",
)


def inspect() -> dict:
	return {
		name: {
			"doctype_exists": bool(frappe.db.exists("DocType", name)),
			"rows": frappe.db.count(name) if frappe.db.exists("DocType", name) else 0,
		}
		for name in TARGET_DOCTYPES
	}


def drop() -> dict:
	state = inspect()
	blocked = {name: value for name, value in state.items() if value["rows"]}
	if blocked:
		frappe.throw(f"Refusing to drop DocTypes with data: {blocked}", frappe.ValidationError)

	removed = []
	for name, value in state.items():
		if not value["doctype_exists"]:
			continue
		frappe.delete_doc("DocType", name, force=True, ignore_permissions=True)
		removed.append(name)
	frappe.db.commit()
	frappe.clear_cache()
	return {"removed": removed, "remaining": inspect()}
