"""Phase 3 automatic lead routing: assigns a newly captured CRM Contact to a
team and an owner within that team, replacing the manual-only assignment
flow. Locked algorithm — round-robin within the team matching the lead's
campus (branch):
1. Pick the active CRM Team whose campus matches the lead's branch (oldest
   first if more than one exists for that campus).
2. Among that team's active staff members, pick whoever was routed longest
   ago (CRM Staff.last_routed_at ascending — NULLs, i.e. never routed, sort
   first in MySQL).
See plans/260822-admissions-crm-alignment/phase-03-lead-status-routing-sla.md.
"""

import frappe
from frappe.utils import now_datetime


def pick_team_for_campus(campus):
	if not campus:
		return None
	return frappe.db.get_value(
		"CRM Team",
		{"campus": campus, "is_active": 1},
		"name",
		order_by="creation asc",
	)


def pick_round_robin_staff(team):
	if not team:
		return None
	staff_in_team = frappe.get_all(
		"CRM Team Membership",
		filters={"team": team, "parenttype": "CRM Staff"},
		pluck="parent",
	)
	if not staff_in_team:
		return None
	return frappe.db.get_value(
		"CRM Staff",
		{"name": ["in", staff_in_team], "is_active": 1},
		"name",
		order_by="last_routed_at asc, creation asc",
	)


def mark_staff_routed(staff):
	frappe.db.set_value("CRM Staff", staff, "last_routed_at", now_datetime(), update_modified=False)


def route_new_lead(doc):
	"""Auto-assigns doc.assigned_to in place if it is a new, unassigned
	CRM Contact with a known campus. No-op (silent, leaves the lead
	unassigned for manual pickup) if no matching team or no active staff is
	found — covers the "no available staff on a team" scenario."""
	if doc.assigned_to or not doc.branch:
		return

	team = pick_team_for_campus(doc.branch)
	if not team:
		return

	staff = pick_round_robin_staff(team)
	if not staff:
		return

	doc.assigned_to = staff
	doc.flags.auto_routed = True
	mark_staff_routed(staff)


@frappe.whitelist()
def route_unassigned_leads(doctype="CRM Contact"):
	"""Batch retry for leads that were captured while no staff was
	available for their team (e.g. via import, or a team with no active
	members at capture time). Safe to call repeatedly/on a schedule."""
	if doctype not in ("CRM Contact",):
		frappe.throw(frappe._("Routing is only supported for CRM Contact."))

	from crm.api.staff_assignment import _has_staff_assign_permission

	if not _has_staff_assign_permission():
		frappe.throw(frappe._("You are not permitted to route leads."), frappe.PermissionError)

	unassigned = frappe.get_all(
		doctype,
		filters={"assigned_to": ["is", "not set"], "branch": ["is", "set"]},
		fields=["name"],
	)
	routed = 0
	for row in unassigned:
		doc = frappe.get_doc(doctype, row.name)
		route_new_lead(doc)
		if doc.assigned_to:
			doc.save(ignore_permissions=True)
			routed += 1

	frappe.db.commit()
	return {"routed": routed, "checked": len(unassigned)}
