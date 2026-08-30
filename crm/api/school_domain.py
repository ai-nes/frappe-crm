from __future__ import annotations

import frappe


@frappe.whitelist()
def get_school_stakeholders(high_school: str, limit: int = 50):
	"""Return school associations with the linked Person identity for the panel."""
	associations = frappe.get_all(
		"CRM School Stakeholder",
		filters={"high_school": high_school},
		fields=[
			"name", "person", "stakeholder_role", "position_title",
			"relationship_status", "influence", "owner_staff", "owning_team",
		],
		order_by="modified desc",
		limit_page_length=min(int(limit or 50), 100),
	)
	person_names = [row.person for row in associations if row.person]
	people = {
		row.name: row
		for row in frappe.get_all(
			"CRM Person",
			filters={"name": ["in", person_names]} if person_names else {"name": "__none__"},
			fields=["name", "full_name", "phone", "email"],
			limit_page_length=0,
		)
	}
	return [
		{
			**row,
			"full_name": people.get(row.person, {}).get("full_name") if row.person else None,
			"phone": people.get(row.person, {}).get("phone") if row.person else None,
			"email": people.get(row.person, {}).get("email") if row.person else None,
		}
		for row in associations
	]
