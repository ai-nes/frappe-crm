import frappe


def execute():
    """Load Frappe CRM workspace from frappe_crm.json fixture with full module layout."""
    frappe.reload_doc("fcrm", "Workspace", "Frappe CRM", force=True)
