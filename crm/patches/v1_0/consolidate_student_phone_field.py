"""
Consolidate mobile_no into phone for CRM Student.
Backfill phone from mobile_no where phone is blank, then drop mobile_no column.
"""

import frappe


def execute():
	# Backfill phone from mobile_no where phone is empty
	frappe.db.sql(
		"""
		UPDATE `tabCRM Student`
		SET phone = mobile_no
		WHERE (phone IS NULL OR phone = '') AND (mobile_no IS NOT NULL AND mobile_no != '')
		"""
	)

	# Drop mobile_no column if it exists
	existing = {row[0] for row in frappe.db.sql("SHOW COLUMNS FROM `tabCRM Student`")}
	if "mobile_no" in existing:
		frappe.db.sql("ALTER TABLE `tabCRM Student` DROP COLUMN `mobile_no`")

	frappe.clear_cache(doctype="CRM Student")
