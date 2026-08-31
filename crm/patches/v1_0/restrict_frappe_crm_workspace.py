"""Restrict the Desk management workspace to System Managers."""

import frappe


def execute():
	frappe.reload_doc("fcrm", "Workspace", "Frappe CRM", force=True)
	frappe.clear_cache()
