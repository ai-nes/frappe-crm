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

from crm.fcrm.role_policy import (
	case_scope_for_roles,
)

# Compatibility export for lifecycle.py only. Row-level Student/Contact access
# no longer reads this set; it resolves the canonical policy below.
FULL_VISIBILITY_ROLES = frozenset(
	{"System Manager", "CRM Manager", "Administrator", "Admissions Director", "Admissions Operations"}
)

CACHE_TTL_SEC = 300


def get_permission_query_conditions(doctype, user=None):
	if not user:
		user = frappe.session.user

	roles = set(frappe.get_roles(user))
	scope = _effective_case_scope(roles, doctype, user=user)
	if scope == "all":
		return None
	if scope == "deny":
		return "1=0"

	crm_staff_name = _get_crm_staff_name(user)
	if not crm_staff_name:
		return "1=0"

	table = f"`tab{doctype}`"

	if frappe.conf.get("crm_legacy_campus_scoping"):
		# Legacy fallback only ever applied to Counseller/Promoter-PR's campus-wide
		# scope; Sale/CTV-Sale keep their own-assigned-only rule even when this flag
		# is set, so flipping it can't silently widen their visibility.
		if scope in {"assigned", "own_assigned"}:
			return f"{table}.assigned_to = {frappe.db.escape(crm_staff_name)}"
		if scope in {"campus_assigned", "campus_assigned_contact"}:
			return _campus_condition(table, crm_staff_name)
		return _team_leader_condition(table, crm_staff_name)

	if scope in {"team_and_team_pool", "team_members_and_own_team_pool"}:
		return _team_leader_condition(table, crm_staff_name)

	if scope in {"campus_assigned", "campus_assigned_contact"}:
		return _campus_condition(table, crm_staff_name)

	if scope in {"assigned", "own_assigned"}:
		return f"{table}.owner_staff = {frappe.db.escape(crm_staff_name)}"

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


def _effective_case_scope(roles, doctype, *, user):
	"""Delegate policy selection; this module only turns a scope into SQL."""
	return case_scope_for_roles(roles, doctype, administrator=user == "Administrator")


def _cached(cache_key, loader):
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	value = loader()
	frappe.cache().set_value(cache_key, value, expires_in_sec=CACHE_TTL_SEC)
	return value


def _get_crm_staff_name(user):
	return (
		_cached(
			f"crm_staff_name::{user}",
			lambda: frappe.db.get_value("CRM Staff", {"user": user}, "name") or "",
		)
		or None
	)


def _get_teams(crm_staff_name):
	return _cached(
		f"crm_staff_teams::{crm_staff_name}",
		lambda: frappe.get_all(
			"CRM Team Membership",
			filters={"parent": crm_staff_name, "parenttype": "CRM Staff"},
			pluck="team",
		),
	)


def _get_teams_in_staff_campus(crm_staff_name):
	"""Restrict membership-derived Team scope to the Staff record's Campus."""
	return _cached(
		f"crm_staff_campus_teams::{crm_staff_name}",
		lambda: _load_teams_in_staff_campus(crm_staff_name),
	)


def _load_teams_in_staff_campus(crm_staff_name):
	campus = frappe.db.get_value("CRM Staff", crm_staff_name, "campus")
	teams = _get_teams(crm_staff_name)
	if not campus or not teams:
		return []
	return frappe.get_all("CRM Team", filters={"name": ["in", teams], "campus": campus}, pluck="name")


def _primary_team(staff_name):
	if not staff_name:
		return None
	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff_name, "parenttype": "CRM Staff"},
		fields=["team", "is_primary"],
		order_by="is_primary desc, creation asc",
	)
	return memberships[0].team if memberships else None


def derive_owner_fields(assigned_to):
	"""Compute (owner_staff, owning_team) for an *assigned* CRM Contact/Student.
	owner_staff simply echoes assigned_to; owning_team is the staff's primary team
	membership (falling back to their first team if none is marked primary).
	Called from CRMContact/CRMStudent.validate() so these two fields — not
	assigned_to/branch — are what row-level scoping keys off of.
	"""
	if not assigned_to:
		return None, None
	return assigned_to, _primary_team(assigned_to)


def derive_unassigned_owning_team(creator_user):
	"""owning_team for a record that has NO assigned_to yet. Without this, an
	unassigned record could never carry a team attribution at all (owner_staff and
	owning_team would both stay null forever), making the Team Leader "own team's
	unassigned pool" rule in the locked BR matrix (constraint 3) permanently
	unreachable. Attributes the record to the *creating* staff member's own primary
	team instead — the natural team-of-record for a freshly-created, not-yet-assigned
	lead. Callers must only apply this when owning_team is not already set, so a
	record that later gets unassigned again keeps falling back into its last-known
	team's pool rather than being re-attributed to whoever happened to touch it.
	"""
	creator_staff = _get_crm_staff_name(creator_user)
	return _primary_team(creator_staff)


def _in_clause(field, values):
	values = [v for v in set(values) if v]
	if not values:
		return None
	escaped = ", ".join(frappe.db.escape(v) for v in values)
	return f"{field} in ({escaped})"


def _team_leader_condition(table, crm_staff_name):
	teams = _get_teams_in_staff_campus(crm_staff_name)
	if not teams:
		return "1=0"

	staff_in_teams = frappe.get_all(
		"CRM Team Membership",
		filters={"team": ["in", teams], "parenttype": "CRM Staff"},
		pluck="parent",
	)

	parts = []
	staff_clause = _in_clause(f"{table}.owner_staff", staff_in_teams)
	if staff_clause:
		parts.append(staff_clause)

	# Unassigned-pool: Contact/Student now carry owning_team directly (Phase 2), so
	# this is an exact match against the leader's own team(s) — no more approximating
	# team ownership via a shared campus, which used to risk leaking a sibling team's
	# unassigned records (constraint 3).
	team_clause = _in_clause(f"{table}.owning_team", teams)
	if team_clause:
		parts.append(f"({table}.owner_staff is null and {team_clause})")

	if not parts:
		return "1=0"
	return "(" + " or ".join(parts) + ")"


def _campus_condition(table, crm_staff_name):
	campus = frappe.db.get_value("CRM Staff", crm_staff_name, "campus")
	if not campus:
		return "1=0"

	staff_in_campus = frappe.get_all("CRM Staff", filters={"campus": campus}, pluck="name")
	clause = _in_clause(f"{table}.owner_staff", staff_in_campus)
	return clause or "1=0"
