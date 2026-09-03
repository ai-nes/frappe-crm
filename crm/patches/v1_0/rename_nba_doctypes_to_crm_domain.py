"""Rename the pre-release NBA DocTypes to the CRM action-domain names."""

import frappe
from frappe.model.rename_doc import rename_doc

RENAMES = (
	("CRM NBA Action", "CRM Action Definition"),
	("CRM NBA Timing Policy", "CRM Timing Policy"),
	("CRM NBA Execution", "CRM Action Execution"),
	("CRM NBA Outcome", "CRM Action Outcome"),
	("CRM NBA Feedback", "CRM Recommendation Feedback"),
)


def execute():
	"""Preserve installed records when the naming convention is upgraded."""
	frappe.flags.ignore_route_conflict_validation = True
	try:
		for old, new in RENAMES:
			if frappe.db.exists("DocType", old) and not frappe.db.exists("DocType", new):
				rename_doc("DocType", old, new)
				frappe.reload_doctype(new, force=True)
	finally:
		frappe.flags.ignore_route_conflict_validation = False
