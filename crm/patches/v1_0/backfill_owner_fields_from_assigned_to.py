"""One-time backfill: populate owner_staff/owning_team on existing CRM Contact and
CRM Student rows, using the same derivation CRMContact/CRMStudent.validate() now
applies on every save (see crm.fcrm.permissions.derive_owner_fields /
derive_unassigned_owning_team):
- Assigned rows (assigned_to set): owner_staff = assigned_to, owning_team = that
  staff's primary team.
- Unassigned rows (assigned_to blank): owner_staff stays null; owning_team is
  attributed to the record's *creator* (Frappe's standard `owner` field)'s own
  primary team, mirroring how CRMContact/CRMStudent.validate() attributes newly
  created unassigned records — without this, pre-existing unassigned rows would
  never surface in any Lead Sale unassigned pool.

Runs after backfill_team_membership_from_staff so CRM Team Membership rows exist to
derive owning_team from. Idempotent — only touches rows where owner_staff/owning_team
are unset, so a rerun is a cheap no-op.
"""

import frappe

DOCTYPES = ["CRM Student", "CRM Lead"]


def _primary_teams(staff_names):
	"""Prefetch one deterministic primary team per staff member."""
	if not staff_names:
		return {}
	rows = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": ["in", sorted(staff_names)], "parenttype": "CRM Staff"},
		fields=["parent", "team", "is_primary", "creation"],
		order_by="parent, is_primary desc, creation asc",
	)
	teams = {}
	for row in rows:
		teams.setdefault(row.parent, row.team)
	return teams


def _bulk_set(doctype, field_values):
	"""Apply grouped updates in bounded SQL batches instead of one query/row."""
	for (owner_staff, owning_team), names in field_values.items():
		for offset in range(0, len(names), 200):
			batch = names[offset : offset + 200]
			placeholders = ", ".join(["%s"] * len(batch))
			frappe.db.sql(
				f"UPDATE `tab{doctype}` SET owner_staff = %s, owning_team = %s "
				f"WHERE name IN ({placeholders})",
				[owner_staff, owning_team, *batch],
			)


def _bulk_set_team(doctype, field_values):
	for owning_team, names in field_values.items():
		for offset in range(0, len(names), 200):
			batch = names[offset : offset + 200]
			placeholders = ", ".join(["%s"] * len(batch))
			frappe.db.sql(
				f"UPDATE `tab{doctype}` SET owning_team = %s WHERE name IN ({placeholders})",
				[owning_team, *batch],
			)


def execute():
	for doctype in DOCTYPES:
		assigned_rows = frappe.get_all(
			doctype,
			filters={"assigned_to": ["is", "set"], "owner_staff": ["is", "not set"]},
			fields=["name", "assigned_to"],
		)
		staff_names = {row.assigned_to for row in assigned_rows if row.assigned_to}
		primary_teams = _primary_teams(staff_names)
		assigned_updates = {}
		for row in assigned_rows:
			assigned_updates.setdefault(
				(row.assigned_to, primary_teams.get(row.assigned_to)), []
			).append(row.name)
		_bulk_set(doctype, assigned_updates)

		unassigned_rows = frappe.get_all(
			doctype,
			filters={"assigned_to": ["is", "not set"], "owning_team": ["is", "not set"]},
			fields=["name", "owner"],
		)
		owner_users = {row.owner for row in unassigned_rows if row.owner}
		staff_rows = frappe.get_all(
			"CRM Staff",
			filters={"user": ["in", sorted(owner_users)]} if owner_users else {"name": "__none__"},
			fields=["user", "name"],
		)
		creator_staff = {row.user: row.name for row in staff_rows if row.user}
		primary_teams.update(_primary_teams(set(creator_staff.values())))
		unassigned_updates = {}
		for row in unassigned_rows:
			owning_team = primary_teams.get(creator_staff.get(row.owner))
			if owning_team:
				unassigned_updates.setdefault(owning_team, []).append(row.name)
		_bulk_set_team(doctype, unassigned_updates)

	frappe.db.commit()
