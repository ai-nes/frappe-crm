"""Add the Group → Team management fields used by dashboard-crm."""

import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_team_group")
	frappe.reload_doc("fcrm", "doctype", "crm_team")
	frappe.clear_cache()
