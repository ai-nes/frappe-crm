import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_ai_personal_email_draft", force=True)
