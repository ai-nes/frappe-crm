"""Shared row-level data-scope logic for CRM Contact and CRM Student.

Implements the locked matrix in plans/260822-admissions-crm-alignment/business-rules-data-scope.md:
- Sale / CTV-Sale        -> own-assigned records only
- Team Leader            -> own team(s) + own team's unassigned pool
- Counseller / Promoter-PR -> team/campus scope (not system-wide)
- System Manager / CRM Manager / Administrator / Admissions Director / Admissions Operations -> full

One doctype-parameterized function is used for both CRM Contact and CRM Student so the two
doctypes can never drift into the two inconsistent mechanisms they had before this phase.

Gated behind site_config `crm_legacy_campus_scoping`: set truthy to fall back to the old
campus-wide-for-everyone condition (pre-Phase-1 behavior) without a code deploy.
"""

import frappe

FULL_VISIBILITY_ROLES = {
	"System Manager",
	"CRM Manager",
	"Administrator",
	"Admissions Director",
	"Admissions Operations",
}

CACHE_TTL_SEC = 300


def get_permission_query_conditions(doctype, user=None):
	if not user:
		user = frappe.session.user

	roles = set(frappe.get_roles(user))
	if FULL_VISIBILITY_ROLES & roles:
		return None

	crm_staff_name = _get_crm_staff_name(user)
	if not crm_staff_name:
		return "1=0"

	table = f"`tab{doctype}`"

	# Deliberately closed to the 5 lead-ownership roles the locked BR matrix defines.
	# Marketing/Admissions roles are handled above via FULL_VISIBILITY_ROLES (bypass)
	# or intentionally excluded (Marketing Operator/Lead have no Contact/Student
	# access in this phase — see business-rules-data-scope.md) — not an omission.
	if frappe.conf.get("crm_legacy_campus_scoping"):
		# Legacy fallback only ever applied to Counseller/Promoter-PR's campus-wide
		# scope; Sale/CTV-Sale keep their own-assigned-only rule even when this flag
		# is set, so flipping it can't silently widen their visibility.
		if "Sale" in roles or "CTV-Sale" in roles:
			return f"{table}.assigned_to = {frappe.db.escape(crm_staff_name)}"
		return _campus_condition(table, crm_staff_name)

	if "Team Leader" in roles:
		return _team_leader_condition(table, crm_staff_name)

	if "Counseller" in roles or "Promoter-PR" in roles:
		return _campus_condition(table, crm_staff_name)

	if "Sale" in roles or "CTV-Sale" in roles:
		return f"{table}.assigned_to = {frappe.db.escape(crm_staff_name)}"

	return "1=0"


def has_permission(doc, user=None, permission_type=None):
	"""Single-document counterpart of get_permission_query_conditions.

	permission_query_conditions only filters list/report-view SQL — Frappe never
	consults it for frappe.get_doc, the desk single-record view, or the REST API's
	GET /api/resource/<doctype>/<name>. Without this hook a scoped-out user could
	still read/write any record directly by name, defeating the locked BR matrix.
	"""
	if not user:
		user = frappe.session.user

	roles = set(frappe.get_roles(user))
	if FULL_VISIBILITY_ROLES & roles:
		return True

	crm_staff_name = _get_crm_staff_name(user)
	if not crm_staff_name:
		return False

	condition = get_permission_query_conditions(doc.doctype, user=user)
	if condition is None:
		return True
	if condition == "1=0":
		return False

	table = f"`tab{doc.doctype}`"
	return bool(
		frappe.db.sql(
			f"select name from {table} where name = %s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def _cached(cache_key, loader):
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	value = loader()
	frappe.cache().set_value(cache_key, value, expires_in_sec=CACHE_TTL_SEC)
	return value


def _get_crm_staff_name(user):
	return _cached(
		f"crm_staff_name::{user}",
		lambda: frappe.db.get_value("CRM Staff", {"user": user}, "name") or "",
	) or None


def _get_teams(crm_staff_name):
	return _cached(
		f"crm_staff_teams::{crm_staff_name}",
		lambda: frappe.get_all(
			"CRM Team Membership",
			filters={"parent": crm_staff_name, "parenttype": "CRM Staff"},
			pluck="team",
		),
	)


def _in_clause(field, values):
	values = [v for v in set(values) if v]
	if not values:
		return None
	escaped = ", ".join(frappe.db.escape(v) for v in values)
	return f"{field} in ({escaped})"


def _team_leader_condition(table, crm_staff_name):
	teams = _get_teams(crm_staff_name)
	if not teams:
		return "1=0"

	staff_in_teams = frappe.get_all(
		"CRM Team Membership",
		filters={"team": ["in", teams], "parenttype": "CRM Staff"},
		pluck="parent",
	)
	team_campuses = frappe.get_all(
		"CRM Team", filters={"name": ["in", teams]}, fields=["name", "campus"]
	)

	parts = []
	staff_clause = _in_clause(f"{table}.assigned_to", staff_in_teams)
	if staff_clause:
		parts.append(staff_clause)

	# Unassigned-pool: Contact/Student have no owning_team field yet (that lands in
	# Phase 2), so an unassigned record can only be attributed to a team via campus
	# match. Only include a campus here if none of the leader's OTHER teams share it
	# with a team outside their own set — otherwise a shared campus could leak a
	# sibling team's unassigned records, which the locked BR matrix forbids
	# (constraint 3: unassigned-pool visibility must be scoped to own team only, not
	# campus-wide). A campus shared with another team is simply omitted from the pool
	# rather than approximated, so this can under-deliver visibility for multi-team
	# campuses but never over-expose.
	own_campuses = {row.campus for row in team_campuses if row.campus}
	exclusive_campuses = [
		campus
		for campus in own_campuses
		if not frappe.get_all(
			"CRM Team", filters={"campus": campus, "name": ["not in", teams]}, limit=1
		)
	]
	pool_clause = _in_clause(f"{table}.branch", exclusive_campuses)
	if pool_clause:
		parts.append(f"({table}.assigned_to is null and {pool_clause})")

	if not parts:
		return "1=0"
	return "(" + " or ".join(parts) + ")"


def _campus_condition(table, crm_staff_name):
	campus = frappe.db.get_value("CRM Staff", crm_staff_name, "campus")
	if not campus:
		return "1=0"

	staff_in_campus = frappe.get_all("CRM Staff", filters={"campus": campus}, pluck="name")
	clause = _in_clause(f"{table}.assigned_to", staff_in_campus)
	return clause or "1=0"
