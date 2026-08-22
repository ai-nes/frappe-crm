"""Phase 5: migrate CRM Contact's legacy singular crm_campaign/crm_event
Link fields into the new many-to-many CRM Campaign Touchpoint / CRM Event
Participation doctypes, so no historical attribution is lost when a lead can
now touch multiple campaigns/events. The old singular fields are kept
populated as a read-only fallback (see their deprecation notes in
crm_contact.json) -- this patch is additive, not destructive.

Idempotent: skips any (campaign, contact) / (event, contact) pair that
already has a touchpoint/participation row. Runs with frappe.flags.in_patch
set by the patch runner, which the interaction_log.py dispatchers check to
avoid generating present-dated interactions for years-old historical touches.
"""

import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_campaign_touchpoint", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_event_participation", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_campaign", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_event", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_contact", force=True)

	_backfill_event_start_datetime()
	_migrate_campaigns()
	_migrate_events()

	frappe.db.commit()


def _backfill_event_start_datetime():
	"""start_datetime is now required on CRM Event; existing rows only have the
	deprecated event_date. Backfill so they don't fail validation on next save."""
	frappe.db.sql(
		"""
		update `tabCRM Event`
		set start_datetime = event_date
		where start_datetime is null and event_date is not null
		"""
	)


def _migrate_campaigns():
	rows = frappe.db.get_all(
		"CRM Contact",
		filters=[["crm_campaign", "is", "set"]],
		fields=["name", "student", "crm_campaign", "creation"],
	)
	for row in rows:
		if frappe.db.exists(
			"CRM Campaign Touchpoint", {"crm_campaign": row.crm_campaign, "crm_contact": row.name}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Campaign Touchpoint",
				"crm_campaign": row.crm_campaign,
				"crm_contact": row.name,
				"student": row.student,
				"touched_at": row.creation,
				"source": "Migrated",
			}
		).insert(ignore_permissions=True)


def _migrate_events():
	rows = frappe.db.get_all(
		"CRM Contact",
		filters=[["crm_event", "is", "set"]],
		fields=["name", "student", "crm_event", "creation"],
	)
	for row in rows:
		if frappe.db.exists(
			"CRM Event Participation", {"crm_event": row.crm_event, "crm_contact": row.name}
		):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Event Participation",
				"crm_event": row.crm_event,
				"crm_contact": row.name,
				"student": row.student,
				"status": "Registered",
				"registered_at": row.creation,
			}
		).insert(ignore_permissions=True)
