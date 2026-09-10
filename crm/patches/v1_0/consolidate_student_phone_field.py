"""
Consolidate mobile_no into phone for CRM Lead.
Backfill phone from mobile_no where phone is blank, then drop mobile_no column.
"""

import frappe


def execute():
	existing = {row[0] for row in frappe.db.sql("SHOW COLUMNS FROM `tabCRM Lead`")}
	if "mobile_no" in existing:
		# Backfill phone from mobile_no where phone is empty
		frappe.db.sql(
			"""
			UPDATE `tabCRM Lead`
			SET phone = mobile_no
			WHERE (phone IS NULL OR phone = '') AND (mobile_no IS NOT NULL AND mobile_no != '')
			"""
		)

		frappe.db.commit()
		frappe.db.sql("ALTER TABLE `tabCRM Lead` DROP COLUMN `mobile_no`")

	frappe.clear_cache(doctype="CRM Lead")
