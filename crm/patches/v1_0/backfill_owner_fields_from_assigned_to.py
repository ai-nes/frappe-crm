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
  never surface in any Team Leader's unassigned pool.

Runs after backfill_team_membership_from_staff so CRM Team Membership rows exist to
derive owning_team from. Idempotent — only touches rows where owner_staff/owning_team
are unset, so a rerun is a cheap no-op.
"""

import frappe

from crm.fcrm.permissions import derive_owner_fields, derive_unassigned_owning_team

DOCTYPES = ["CRM Contact", "CRM Student"]


def execute():
	for doctype in DOCTYPES:
		assigned_rows = frappe.get_all(
			doctype,
			filters={"assigned_to": ["is", "set"], "owner_staff": ["is", "not set"]},
			fields=["name", "assigned_to"],
		)
		for row in assigned_rows:
			owner_staff, owning_team = derive_owner_fields(row.assigned_to)
			frappe.db.set_value(
				doctype,
				row.name,
				{"owner_staff": owner_staff, "owning_team": owning_team},
				update_modified=False,
			)

		unassigned_rows = frappe.get_all(
			doctype,
			filters={"assigned_to": ["is", "not set"], "owning_team": ["is", "not set"]},
			fields=["name", "owner"],
		)
		for row in unassigned_rows:
			owning_team = derive_unassigned_owning_team(row.owner)
			if owning_team:
				frappe.db.set_value(doctype, row.name, "owning_team", owning_team, update_modified=False)

	frappe.db.commit()
