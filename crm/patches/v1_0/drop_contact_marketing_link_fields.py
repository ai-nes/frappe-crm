"""
Drop CRM Student.crm_campaign / crm_event columns.

These were direct Link shortcuts superseded by CRM Marketing Engagement.
The `migrate_campaign_event_to_many_to_many` patch backfills any remaining
legacy values before this patch runs (enforced by patches.txt ordering).
"""

import frappe

COLUMNS = {
	"CRM Student": ["crm_campaign", "crm_event"],
}


def execute():
	for doctype, columns in COLUMNS.items():
		if not frappe.db.table_exists(doctype):
			continue
		existing = {row[0] for row in frappe.db.sql(f"SHOW COLUMNS FROM `tab{doctype}`")}
		for col in columns:
			if col in existing:
				frappe.db.sql(f"ALTER TABLE `tab{doctype}` DROP COLUMN `{col}`")
		frappe.clear_cache(doctype=doctype)
