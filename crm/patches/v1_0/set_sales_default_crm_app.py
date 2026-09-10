"""Set the CRM application as the default landing route for Sales users."""

import frappe


def execute():
	users = frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", ["Sale", "Lead Sale"]]},
		pluck="parent",
	)
	for user in frappe.get_all("User", filters={"name": ["in", sorted(set(users))]}, fields=["name", "default_app"]):
		if not user.default_app:
			frappe.db.set_value("User", user.name, "default_app", "crm", update_modified=False)
	frappe.clear_cache()
