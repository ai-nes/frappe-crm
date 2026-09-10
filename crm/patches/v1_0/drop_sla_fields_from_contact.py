"""
Remove SLA and communication_status fields from CRM Student.
These B2B customer-service fields are not applicable to education admissions CRM.
"""

import frappe


SLA_COLUMNS = [
	"communication_status",
	"sla_status",
	"sla",
	"sla_creation",
	"response_by",
	"first_responded_on",
	"first_response_time",
	"last_responded_on",
	"last_response_time",
]


def execute():
	existing = {
		row[0]
		for row in frappe.db.sql("SHOW COLUMNS FROM `tabCRM Student`")
	}
	for col in SLA_COLUMNS:
		if col in existing:
			frappe.db.sql(f"ALTER TABLE `tabCRM Student` DROP COLUMN `{col}`")

	# rolling_responses child table
	if frappe.db.table_exists("tabRolling Response Time"):
		frappe.db.sql("DELETE FROM `tabRolling Response Time` WHERE parenttype = 'CRM Student'")

	frappe.clear_cache(doctype="CRM Student")
