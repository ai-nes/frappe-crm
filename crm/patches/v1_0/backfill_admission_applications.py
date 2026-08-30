"""Rerunnable Student → Application backfill with a review outcome for gaps."""

from __future__ import annotations

import frappe

from crm.fcrm.admission_application_migration import application_backfill_decision


def execute():
	if not frappe.db.exists("DocType", "CRM Admission Application") or not frappe.db.exists("DocType", "CRM Student"):
		return {"mode": "skipped", "reason": "doctype_unavailable"}
	if not frappe.db.exists("DocType", "CRM Admission Offering") or not frappe.db.exists("DocType", "CRM Student Case Key"):
		return {"mode": "blocked", "reason": "canonical_offering_or_case_key_unavailable"}

	rows = frappe.get_all(
		"CRM Student",
		fields=["name", "case_key", "admission_year", "major", "branch", "admission_method", "enrollment_status"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	existing = set(frappe.get_all("CRM Admission Application", pluck="idempotency_fingerprint", ignore_permissions=True))
	offerings = frappe.get_all(
		"CRM Admission Offering",
		fields=["name", "admission_year", "campus", "major", "admission_method", "status"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	counts = {"migrated": 0, "existing": 0, "review": 0}
	for row in rows:
		decision = application_backfill_decision(row, existing, offerings)
		outcome = decision["outcome"]
		counts[outcome] = counts.get(outcome, 0) + 1
		if outcome != "migrated":
			continue
		values = {"doctype": "CRM Admission Application", **decision["values"]}
		values.update({key: decision[key] for key in ("schema_version", "source_doctype", "source_name", "source_reference", "idempotency_fingerprint")})
		frappe.get_doc(values).insert(ignore_permissions=True)
		existing.add(decision["idempotency_fingerprint"])
	frappe.db.commit()
	return {"mode": "applied", "counts": counts}
