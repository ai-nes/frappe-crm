"""Create the dedicated role used to manage the Frappe CRM Rule registry."""

import frappe

from crm.fcrm.role_policy import BUSINESS_ADMIN_ROLE


def execute():
	if frappe.db.exists("Role", BUSINESS_ADMIN_ROLE):
		return
	frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": BUSINESS_ADMIN_ROLE,
			"desk_access": 1,
		}
	).insert(ignore_permissions=True)
