import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_ai_lead_insight_interest", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_ai_lead_insight_objection", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_ai_lead_insight_risk_flag", force=True)
	frappe.reload_doc("fcrm", "doctype", "crm_ai_lead_insight", force=True)
