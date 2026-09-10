"""
Drop columns for fields removed as dead legacy code:

- CRM Action Item.nba_action: superseded by `action` (CRM Action link);
  the field was write-blocked but never read anywhere.
- CRM Target.scope_type / scope: former free-text scope selectors,
  superseded by the `planning_scope` Link; every writer set them to
  ``None`` and no reader used them for a real decision.
"""

import frappe

COLUMNS = {
	"CRM Action Item": ["nba_action"],
	"CRM Target": ["scope_type", "scope"],
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
