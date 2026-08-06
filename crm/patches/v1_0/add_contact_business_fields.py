import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_contact", force=True)
