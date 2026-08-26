"""Keep Student-related data dark until the staged delegated scope gates pass."""

import frappe


def execute():
	if frappe.db.has_column("DocType", "custom_ai_exposed"):
		frappe.db.sql(
			"UPDATE `tabDocType` SET custom_ai_exposed = 0 "
			"WHERE name IN ('CRM Student', 'CRM Intent', 'CRM Interaction')"
		)
