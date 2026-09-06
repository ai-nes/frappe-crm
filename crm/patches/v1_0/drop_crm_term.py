"""Remove the retired CRM Term GOD doctype and its residual references."""

import frappe

DOCTYPE = "CRM Term"


def execute():
	if frappe.db.exists("DocType", DOCTYPE):
		frappe.delete_doc("DocType", DOCTYPE, force=True, ignore_permissions=True)
	frappe.db.sql_ddl("DROP TABLE IF EXISTS `tabCRM Term`")

	if frappe.db.exists("DocType", "CRM Master Data Change"):
		frappe.db.delete("CRM Master Data Change", {"reference_doctype": DOCTYPE})

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
