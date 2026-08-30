"""Reload the Desk workspace after adding its role restriction."""

import frappe


def execute():
	frappe.reload_doc("fcrm", "Workspace", "Frappe CRM", force=True)
	frappe.clear_cache()
