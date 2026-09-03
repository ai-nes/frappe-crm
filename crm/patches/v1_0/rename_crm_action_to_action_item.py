"""Move the historical student-scoped CRM Action aggregate to CRM Action Item."""

import frappe
from frappe.model.rename_doc import rename_doc


def execute():
	"""Preserve existing work-item rows before CRM Action becomes the master catalog."""
	if frappe.db.exists("DocType", "CRM Action") and not frappe.db.exists("DocType", "CRM Action Item"):
		frappe.flags.ignore_route_conflict_validation = True
		try:
			rename_doc("DocType", "CRM Action", "CRM Action Item")
			frappe.reload_doctype("CRM Action Item", force=True)
		finally:
			frappe.flags.ignore_route_conflict_validation = False
