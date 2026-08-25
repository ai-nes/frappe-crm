"""Create one explicit Student pool for each active Sales Team."""

import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Student Pool"):
		return
	for team in frappe.get_all(
		"CRM Team",
		filters={"team_type": "Sales", "is_active": 1},
		fields=["name", "team_name", "campus"],
	):
		if not team.get("campus"):
			continue
		if frappe.db.exists("CRM Student Pool", {"team": team.name, "campus": team.campus}):
			continue
		pool_name = f"{team.get('team_name') or team.name} Pool"
		if frappe.db.exists("CRM Student Pool", pool_name):
			continue
		frappe.get_doc(
			{
				"doctype": "CRM Student Pool",
				"pool_name": pool_name,
				"team": team.name,
				"campus": team.campus,
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
