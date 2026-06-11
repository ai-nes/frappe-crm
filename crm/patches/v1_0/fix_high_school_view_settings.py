import json

import frappe

from crm.install import add_default_quick_filters


def execute():
	"""Remove stale Organization list views and reset broken High School views."""
	for name in frappe.get_all("View Settings", filters={"dt": "CRM Organization"}, pluck="name"):
		frappe.delete_doc("View Settings", name, force=True)

	stale_row_fields = {
		"organization_name",
		"organization_logo",
		"website",
		"industry",
		"currency",
		"annual_revenue",
		"territory",
	}

	for view in frappe.get_all(
		"View Settings",
		filters={"dt": "CRM High School"},
		fields=["name", "rows", "route_name"],
	):
		rows = json.loads(view.rows or "[]")
		if rows and stale_row_fields.intersection(rows):
			frappe.delete_doc("View Settings", view.name, force=True)
			continue

		if view.route_name in ("Organizations", None, ""):
			frappe.db.set_value("View Settings", view.name, "route_name", "High Schools")

	for view in frappe.get_all(
		"View Settings",
		filters={"route_name": "Organizations"},
		fields=["name"],
	):
		frappe.delete_doc("View Settings", view.name, force=True)

	add_default_quick_filters()
