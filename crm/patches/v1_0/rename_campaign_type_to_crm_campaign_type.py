import frappe
from frappe.model.rename_doc import rename_doc


def execute():
	frappe.flags.ignore_route_conflict_validation = True

	try:
		if frappe.db.exists("DocType", "Campaign Type") and not frappe.db.exists("DocType", "CRM Campaign Type"):
			rename_doc("DocType", "Campaign Type", "CRM Campaign Type")
			frappe.reload_doctype("CRM Campaign Type", force=True)
	finally:
		frappe.flags.ignore_route_conflict_validation = False
