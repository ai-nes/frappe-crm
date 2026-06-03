import frappe


def execute():
	"""Replace stale Frappe CRM workspace shortcuts (e.g. CRM Communication Status)."""
	frappe.reload_doc("fcrm", "Workspace", "Frappe CRM", force=True)
