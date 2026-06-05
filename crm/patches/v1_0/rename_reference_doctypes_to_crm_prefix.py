import frappe
from frappe.model.rename_doc import rename_doc


RENAMES = (
	("Academic Year Config", "CRM Academic Year Config"),
	("Admission Year", "CRM Admission Year"),
	("Campus", "CRM Campus"),
	("Major Group", "CRM Major Group"),
)


def execute():
	frappe.flags.ignore_route_conflict_validation = True

	try:
		for old, new in RENAMES:
			if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
				rename_doc("DocType", old, new)
				frappe.reload_doctype(new, force=True)
	finally:
		frappe.flags.ignore_route_conflict_validation = False
