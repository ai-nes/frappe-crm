import frappe
from frappe.model.rename_doc import rename_doc


def execute():
	frappe.flags.ignore_route_conflict_validation = True

	doctypes = (
		("Campaign", "CRM Campaign"),
		("Department", "CRM Department"),
		("Influence", "CRM Influence"),
		("Person", "CRM Person"),
		("Staff", "CRM Staff"),
	)

	try:
		for old, new in doctypes:
			if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
				rename_doc("DocType", old, new)
				frappe.reload_doctype(new, force=True)
	finally:
		frappe.flags.ignore_route_conflict_validation = False
