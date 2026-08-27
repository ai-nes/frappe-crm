"""Remove the unused student/contact conversion reconciliation stub."""

from __future__ import annotations

import frappe

DOCTYPE = "CRM Student Contact Conversion Reconciliation"


def execute():
	if frappe.db.exists("DocType", DOCTYPE):
		frappe.delete_doc("DocType", DOCTYPE, ignore_permissions=True, force=True)
	if frappe.db.table_exists(DOCTYPE):
		frappe.db.sql_ddl(f"DROP TABLE `tab{DOCTYPE}`")
	return {"doctype": DOCTYPE, "status": "dropped"}
