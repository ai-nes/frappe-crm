"""One-time backfill: convert each CRM Staff's legacy sales_team/campus/department
Select fields into an equivalent CRM Team + CRM Team Membership record.

Idempotent — skips staff who already have a membership for the derived team, so
reruns (or a bulk import that calls this again) never duplicate rows. Old fields
are left untouched (deprecated, not deleted) per Phase 1 plan Step 4.
"""

import frappe

# Precedence order mirrors crm.fcrm.permissions scope precedence: broadest role wins
# when a staff member happens to hold more than one CRM role.
FUNCTION_PRECEDENCE = ["Team Leader", "Counseller", "Sale", "CTV-Sale", "Promoter-PR"]


def execute():
	staff_list = frappe.get_all(
		"CRM Staff",
		fields=["name", "sales_team", "campus", "user"],
	)

	existing_teams = set(frappe.get_all("CRM Team", pluck="name"))
	already_migrated = {
		(row.parent, row.team)
		for row in frappe.get_all(
			"CRM Team Membership",
			filters={"parenttype": "CRM Staff"},
			fields=["parent", "team"],
		)
	}
	role_cache = {}

	for staff in staff_list:
		if not staff.campus:
			continue

		team_label = staff.sales_team or "General"
		team_name = f"{team_label} - {staff.campus}"

		if team_name not in existing_teams:
			frappe.get_doc({
				"doctype": "CRM Team",
				"team_name": team_name,
				"team_type": "Sales",
				"campus": staff.campus,
				"is_active": 1,
			}).insert(ignore_permissions=True)
			existing_teams.add(team_name)

		if (staff.name, team_name) in already_migrated:
			continue

		if staff.user not in role_cache:
			role_cache[staff.user] = frappe.get_roles(staff.user) if staff.user else []
		user_roles = role_cache[staff.user]

		function = next(
			(f for f in FUNCTION_PRECEDENCE if f in user_roles),
			"Sale",
		)

		staff_doc = frappe.get_doc("CRM Staff", staff.name)
		staff_doc.append("team_memberships", {
			"team": team_name,
			"function": function,
			"term": "",
			"is_primary": 1,
			"is_team_lead": function == "Team Leader",
		})
		staff_doc.save(ignore_permissions=True)

	frappe.db.commit()
