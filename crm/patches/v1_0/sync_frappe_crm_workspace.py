import frappe


def execute():
	frappe.reload_doc("fcrm", "Workspace", "Frappe CRM", force=True)
