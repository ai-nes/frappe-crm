"""Place legacy ungrouped routing Teams under a visible management Group."""

import frappe

DEFAULT_GROUP_NAME = "Nhóm chưa thiết lập"


def execute():
	legacy_teams = frappe.get_all(
		"CRM Team",
		filters={"group": ["is", "not set"]},
		pluck="name",
		limit_page_length=0,
	)
	if not legacy_teams:
		return

	group = frappe.db.exists("CRM Team Group", DEFAULT_GROUP_NAME)
	if not group:
		group = (
			frappe.get_doc(
				{
					"doctype": "CRM Team Group",
					"group_name": DEFAULT_GROUP_NAME,
					# This is a visibility bucket for legacy rows, not a routable
					# province Group. An administrator must complete it before use.
					"is_active": 0,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	for team_name in legacy_teams:
		frappe.db.set_value("CRM Team", team_name, "group", group, update_modified=False)
