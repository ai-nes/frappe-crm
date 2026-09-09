"""Create opaque internal IDs for existing CRM Leads."""

import uuid

import frappe


def execute():
	rows = frappe.db.sql(
		"SELECT name FROM `tabCRM Lead` WHERE lead_id IS NULL OR lead_id = ''",
		as_dict=True,
	)
	for row in rows:
		lead_id = uuid.uuid4().hex
		while frappe.db.exists("CRM Lead", {"lead_id": lead_id}):
			lead_id = uuid.uuid4().hex
		frappe.db.set_value("CRM Lead", row["name"], "lead_id", lead_id, update_modified=False)
