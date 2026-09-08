"""Add the Province boundary to CRM Team Group."""

import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_team_group")
	frappe.clear_cache()
