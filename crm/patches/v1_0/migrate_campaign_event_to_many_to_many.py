"""Migrate Contact shortcuts into canonical Marketing Engagement records."""

from __future__ import annotations

import frappe


TARGET = "CRM Marketing Engagement"


def _insert(values):
	previous = getattr(frappe.flags, "student_attribution_migration", False)
	frappe.flags.student_attribution_migration = True
	try:
		frappe.get_doc(values).db_insert(ignore_if_duplicate=True)
	finally:
		frappe.flags.student_attribution_migration = previous


def execute():
	if not frappe.db.exists("DocType", TARGET):
		return {"migrated": 0, "status": "canonical_doctype_not_installed"}
	frappe.reload_doc("fcrm", "doctype", "crm_marketing_engagement", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_campaign", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_event", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_contact", force=True)
	created = _migrate_campaigns() + _migrate_events()
	frappe.db.commit()
	return {"migrated": created}


def _migrate_campaigns():
	created = 0
	for row in frappe.db.get_all("CRM Student", filters=[["crm_campaign", "is", "set"]], fields=["name", "student", "crm_campaign", "creation"]):
		if not row.student or frappe.db.exists(TARGET, {"engagement_kind": "campaign_touch", "crm_campaign": row.crm_campaign, "crm_contact": row.name}):
			continue
		_insert({
			"doctype": TARGET, "engagement_kind": "campaign_touch", "reference_doctype": "CRM Campaign",
			"reference_name": row.crm_campaign, "crm_campaign": row.crm_campaign, "crm_contact": row.name,
			"student": row.student, "touched_at": row.creation, "source": "Migrated",
			"creation": row.creation, "modified": row.creation,
		})
		created += 1
	return created


def _migrate_events():
	created = 0
	for row in frappe.db.get_all("CRM Student", filters=[["crm_event", "is", "set"]], fields=["name", "student", "crm_event", "creation"]):
		if not row.student or frappe.db.exists(TARGET, {"engagement_kind": "event_participation", "crm_event": row.crm_event, "crm_contact": row.name}):
			continue
		_insert({
			"doctype": TARGET, "engagement_kind": "event_participation", "reference_doctype": "CRM Event",
			"reference_name": row.crm_event, "crm_event": row.crm_event, "crm_contact": row.name,
			"student": row.student, "status": "Registered", "registered_at": row.creation,
			"creation": row.creation, "modified": row.creation,
		})
		created += 1
	return created


def _backfill_event_start_datetime():
	"""Backfill the canonical Event start from legacy event_date, idempotently."""
	if not frappe.db.exists("DocType", "CRM Event"):
		return 0
	rows = frappe.db.sql(
		"select name, event_date from `tabCRM Event` where (start_datetime is null or start_datetime='') and event_date is not null",
		as_dict=True,
	)
	for row in rows:
		frappe.db.set_value("CRM Event", row.name, "start_datetime", f"{row.event_date} 00:00:00", update_modified=False)
	return len(rows)
