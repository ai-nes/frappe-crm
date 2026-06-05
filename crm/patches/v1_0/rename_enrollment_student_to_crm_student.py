import frappe
from frappe.model.rename_doc import rename_doc


def execute():
	frappe.flags.ignore_route_conflict_validation = True

	try:
		if frappe.db.exists("DocType", "Enrollment Student") and not frappe.db.exists("DocType", "CRM Student"):
			rename_doc("DocType", "Enrollment Student", "CRM Student")
			frappe.reload_doctype("CRM Student", force=True)
	finally:
		frappe.flags.ignore_route_conflict_validation = False
