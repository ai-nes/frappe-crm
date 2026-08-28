"""Deterministic, local-only fixture data for Director analytics.

Run through ``crm.demo.seed_local_admissions.execute``.  This module deliberately
does not create feature flags, credentials, or network connections.  It uses the
same admissions cohort and policy services as the local walkthrough, then adds
only canonical master-data records that the analytics providers can read.
"""

from __future__ import annotations

from datetime import date

import frappe

from crm.demo import seed_admissions_cohort

LOCAL_SITE = "crm.localhost"
NAMESPACE = "director-analytics-local-2026"
ACADEMIC_CONFIG_NAME = "Director analytics local fixture — 2026"

# These costs are intentionally recorded, not approved.  Marketing ROI must
# therefore surface its recorded-cost warning instead of presenting them as an
# approved finance source.
RECORDED_SPEND_ROWS = (
	{"spend_date": date(2026, 5, 15), "amount": 18_000_000, "impressions": 42_000, "clicks": 1_050},
	{"spend_date": date(2026, 6, 15), "amount": 21_500_000, "impressions": 48_000, "clicks": 1_180},
	{"spend_date": date(2026, 7, 15), "amount": 19_750_000, "impressions": 44_000, "clicks": 1_090},
)

ACADEMIC_LINES = (
	{"line_kind": "tuition", "amount": 32_500_000, "note": "Học phí ghi nhận cho dashboard local"},
	{"line_kind": "quota", "quota": 180, "note": "Chỉ tiêu tuyển sinh campus local"},
)


def _assert_local_site() -> None:
	if frappe.local.site != LOCAL_SITE:
		frappe.throw("The Director analytics seed only runs on crm.localhost.", frappe.PermissionError)


def execute(*, admissions: dict, context: dict, staff_context: dict) -> dict:
	"""Seed an idempotent local analytics fixture and return its safe manifest."""
	_assert_local_site()
	frappe.set_user("Administrator")

	# The caller has already seeded this state through the admissions services.
	# Reuse its manifest rather than replaying append-only SLA/lifecycle writes.
	spend = _ensure_recorded_spend(context, staff_context)
	academic = _ensure_academic_year_config(context, staff_context)
	pending_change = _pending_change_manifest()

	frappe.db.commit()
	return {
		"namespace": NAMESPACE,
		"campus": staff_context["campus"],
		"cohort": {
			"students": len(admissions["students"]),
			"sla_statuses": sorted({row["sla_status"] for row in admissions["sla_showcase"]}),
			"lifecycle_stages": sorted({row["target_stage"] for row in seed_admissions_cohort.SCENARIOS}),
		},
		"recorded_campaign_spend": spend,
		"academic_year": academic,
		"pending_master_data_change": pending_change,
		"policy_fixtures": {
			"routing_policy_key": f"{seed_admissions_cohort.NAMESPACE}-routing-v1",
			"sla_policy_key": f"{seed_admissions_cohort.NAMESPACE}-sla-v1",
		},
		# There is no canonical Metabase configuration in this app today.  Do not
		# invent a URL, report ID, secret, or external request merely for a demo.
		"metabase_catalog": _metabase_catalog_fixture(),
	}


def _ensure_recorded_spend(context: dict, staff_context: dict) -> list[str]:
	"""Create stable recorded-cost rows without implying finance approval."""
	if not frappe.db.table_exists("CRM Campaign Spend"):
		return []

	created_or_existing = []
	for row in RECORDED_SPEND_ROWS:
		note = f"{NAMESPACE}: recorded cost; finance approval unavailable"
		existing = frappe.db.get_value(
			"CRM Campaign Spend", {"spend_date": row["spend_date"], "notes": note}, "name"
		)
		if not existing:
			existing = frappe.get_doc(
				{
					"doctype": "CRM Campaign Spend",
					"spend_date": row["spend_date"],
					"lead_source": context["source"],
					"crm_campaign": context["campaign"],
					"campus": staff_context["campus"],
					"amount": row["amount"],
					"impressions": row["impressions"],
					"clicks": row["clicks"],
					"notes": note,
				}
			).insert(ignore_permissions=True).name
		created_or_existing.append(existing)
	return created_or_existing


def _namespaced_academic_line(line: dict, context: dict, staff_context: dict) -> dict:
	return {
		**line,
		"major": context["major"],
		"campus": staff_context["campus"],
		"note": f"{NAMESPACE}: {line['note']}",
	}


def _ensure_academic_year_config(context: dict, staff_context: dict) -> dict:
	"""Ensure this fixture's namespaced quota and tuition lines exist exactly once."""
	if not frappe.db.table_exists("CRM Academic Year Config"):
		return {"status": "unavailable"}

	admission_year = context["admission_year"]
	name = frappe.db.get_value("CRM Academic Year Config", {"admission_year": admission_year}, "name")
	if name:
		doc = frappe.get_doc("CRM Academic Year Config", name)
		status = "existing"
	else:
		doc = frappe.get_doc(
			{
				"doctype": "CRM Academic Year Config",
				"admission_year": admission_year,
				"config_name": ACADEMIC_CONFIG_NAME,
				"notes": "Local-only Director analytics quota and tuition fixture.",
			}
		)
		status = "seeded"

	existing_notes = {row.note for row in doc.lines}
	missing_lines = [
		_namespaced_academic_line(line, context, staff_context)
		for line in ACADEMIC_LINES
		if f"{NAMESPACE}: {line['note']}" not in existing_notes
	]
	if missing_lines:
		for line in missing_lines:
			doc.append("lines", line)
		if doc.is_new():
			doc.insert(ignore_permissions=True)
		else:
			doc.save(ignore_permissions=True)
		status = "seeded" if status == "seeded" else "updated"
	return {
		"status": status,
		"name": doc.name,
		"admission_year": admission_year,
		"line_kinds": sorted(row.line_kind for row in doc.lines if row.note.startswith(NAMESPACE)),
	}


def _pending_change_manifest() -> dict:
	"""Expose the cohort's canonical pending governance request without duplicating it."""
	if not frappe.db.table_exists("CRM Master Data Change"):
		return {"status": "unavailable"}
	name = frappe.db.get_value(
		"CRM Master Data Change", {"idempotency_key": f"{seed_admissions_cohort.NAMESPACE}:mdc:can-tho-campus"}, "name"
	)
	return {"status": "available" if name else "unavailable", "name": name}


def _metabase_catalog_fixture() -> dict:
	"""Return a catalog marker only; never store credentials or call Metabase."""
	canonical_config = "CRM Metabase Report"
	return {"status": "unavailable", "reason": "canonical_config_missing"} if not frappe.db.table_exists(canonical_config) else {
		"status": "available",
		"doctype": canonical_config,
		"reports": [],
	}
