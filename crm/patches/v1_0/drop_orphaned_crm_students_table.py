"""Remove the empty table left by the interrupted plural DocType sync."""

import frappe

TABLE_NAME = "CRM Students"


def execute():
	if frappe.db.exists("DocType", TABLE_NAME) or not frappe.db.table_exists(TABLE_NAME):
		return
	if frappe.db.count(TABLE_NAME):
		frappe.throw(
			"The orphaned CRM Students table contains data and cannot be removed automatically.",
			frappe.ValidationError,
		)
	frappe.db.sql("DROP TABLE `tabCRM Students`")
