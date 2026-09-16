import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_lead", force=True)
	frappe.clear_cache(doctype="CRM Lead")
