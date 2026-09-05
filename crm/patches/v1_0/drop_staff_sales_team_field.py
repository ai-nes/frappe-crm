"""
Drop CRM Staff.sales_team column.

Deprecated free-text Select field, superseded by CRM Team + CRM Team
Membership. The `backfill_team_membership_from_staff` patch already converted
every staff member's legacy sales_team/campus into an equivalent CRM Team
Membership row, and no seed script or reader has written this field since.
"""

import frappe

COLUMNS = {
	"CRM Staff": ["sales_team"],
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
