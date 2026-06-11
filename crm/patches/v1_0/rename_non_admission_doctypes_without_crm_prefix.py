import frappe
from frappe.model.rename_doc import rename_doc


RENAMES = (
	("CRM Call Log", "Call Log"),
	("CRM Dashboard", "Dashboard"),
	("CRM Dropdown Item", "Dropdown Item"),
	("CRM Exotel Settings", "Exotel Settings"),
	("CRM Fields Layout", "Fields Layout"),
	("CRM Form Script", "Form Script"),
	("CRM Global Settings", "Global Settings"),
	("CRM Holiday", "Holiday"),
	("CRM Holiday List", "Holiday List"),
	("CRM Invitation", "Invitation"),
	("CRM Notification", "Notification"),
	("CRM Rolling Response Time", "Rolling Response Time"),
	("CRM Service Day", "Service Day"),
	("CRM Service Level Agreement", "Service Level Agreement"),
	("CRM Service Level Priority", "Service Level Priority"),
	("CRM Status Change Log", "Status Change Log"),
	("CRM Task", "Task"),
	("CRM Telephony Agent", "Telephony Agent"),
	("CRM Telephony Phone", "Telephony Phone"),
	("CRM Twilio Settings", "Twilio Settings"),
	("CRM View Settings", "View Settings"),
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
