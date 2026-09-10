"""Compatibility surface for the retired campus-only router.

The core admissions refactor assigns persisted ``CRM Lead`` rows through an
explicit batch and the canonical zone/capacity service.  The helpers below are
kept temporarily for old imports/tests, but ``route_new_lead`` deliberately
does not mutate a record anymore.

The old algorithm was round-robin within the team matching the lead's campus:
1. Pick the active CRM Team whose campus matches the lead's branch (oldest
   first if more than one exists for that campus).
2. Among that team's active staff members, pick whoever was routed longest
   ago (CRM Staff.last_routed_at ascending — NULLs, i.e. never routed, sort
   first in MySQL).
The routing contract is enforced by this module's selection rules.
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
	"""Deprecated compatibility no-op; assignment requires an explicit batch."""
	return {
		"status": "deferred",
		"reason": "BATCH_REQUIRED",
		"lead": getattr(doc, "name", None),
	}


@frappe.whitelist()
def route_unassigned_leads(doctype="CRM Lead"):
	"""Retained endpoint that explains the new explicit-batch contract."""
	if doctype not in ("CRM Lead", "CRM Student"):
		frappe.throw(frappe._("Routing is only supported for CRM Lead."))

	from crm.api.staff_assignment import _has_staff_assign_permission

	if not _has_staff_assign_permission():
		frappe.throw(frappe._("You are not permitted to route leads."), frappe.PermissionError)

	return {
		"routed": 0,
		"checked": 0,
		"status": "deferred",
		"reason": "BATCH_REQUIRED",
		"message": frappe._("Create or select a Lead Assignment Batch before routing."),
	}
