"""Shared row-level data-scope logic for CRM Contact and CRM Student.

Implements the locked row-level data-scope matrix:
- Sale / CTV Sale        -> own-assigned records only for direct CRUD/detail
- Lead Sale              -> own team(s) + own team's unassigned pool
- System Manager / CRM Manager / Administrator / Admissions Director -> full

The Sale and Lead Sale list projections are intentionally handled by dashboard
APIs as separate read-only Group/Team/pool views because those profiles have
assignment authority. Neither projection changes the canonical CRUD/detail
scope.

One doctype-parameterized function is used for both CRM Contact and CRM Student so the two
doctypes can never drift into the two inconsistent mechanisms they had before this phase.

Gated behind site_config `crm_legacy_campus_scoping`: set truthy to fall back to the old
campus-wide-for-everyone condition (pre-Phase-1 behavior) without a code deploy.
"""

import frappe

from crm.fcrm.role_policy import (
	case_scope_for_roles,
	delete_requires_ownership_for_roles,
	resolve_crm_profile,
)

# Compatibility export for lifecycle.py only. Row-level Student/Contact access
# no longer reads this set; it resolves the canonical policy below.
FULL_VISIBILITY_ROLES = frozenset({"System Manager", "CRM Manager", "Administrator", "Admissions Director"})

CACHE_TTL_SEC = 300

# Operational records are never independently scoped.  They inherit the
# current Student scope and are exposed only through masked service projections.
OPERATIONAL_RECORD_STUDENT_FIELDS = {
	"CRM Student Ownership Event": "student",
	"CRM Student Lifecycle Event": "student",
	"CRM Student Outcome": "student",
	"CRM Student Routing Request": "student",
	"CRM Student SLA Attempt": "student",
	"CRM Student SLA Event": "student",
	"CRM Student SLA Delivery": "student",
	# CRM Score History's `student` link is reqd (crm_score_history.json), so
	# the Student-scope-inheriting condition applies directly. CRM Intent is
	# NOT listed here even though it also has a `student` field: that field is
	# read_only and derived from its (required) `interaction`'s student, so it
	# is null for a Contact-only, pre-conversion interaction -- see
	# get_intent_permission_query_conditions below, which falls back through
	# the parent Interaction's own Student/Contact scope instead of requiring
	# a non-null student.
	"CRM Score History": "student",
	"CRM Student Geography Snapshot": "student",
	"CRM Admission Application": "student",
	"CRM Student Payment": "student",
	"CRM Revenue Recognition": "student",
}


def get_operational_record_permission_query_conditions(user=None, doctype=None):
	"""Scope operational records through their linked Student aggregate."""
	if doctype in {"CRM Action Execution", "CRM Action Outcome", "CRM Recommendation Feedback"}:
		return _nba_operational_permission_query_conditions(user=user, doctype=doctype)
	student_field = OPERATIONAL_RECORD_STUDENT_FIELDS.get(doctype)
	if not student_field:
		return "1=0"
	student_condition = get_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	if student_condition == "1=0":
		return "1=0"
	return (
		f"`tab{doctype}`.`{student_field}` in "
		f"(select `tabCRM Student`.`name` from `tabCRM Student` "
		f"where ({student_condition}))"
	)


def has_operational_record_permission(doc, user=None, permission_type=None, ptype=None):
	"""Apply Student current-scope checks to direct operational-record reads.

	Accepts both `ptype` and `permission_type`: frappe/__init__.py's has_permission
	calls doctype has_permission hooks via frappe.call(method, doc=doc, ptype=ptype,
	user=user, debug=debug) -- frappe.call's get_newargs() silently drops any kwarg
	whose name doesn't match a parameter on the target function, so a hook that only
	declares `permission_type` never actually receives the real value at all.
	"""
	permission_type = permission_type or ptype
	if permission_type == "create":
		# Frappe's has_permission hook fires on Document.insert()'s "create"
		# check before the doctype's autoname assigns doc.name, so the row-scope
		# query below (keyed on name) can't run yet. Row-level scoping still
		# applies to every subsequent read/write once the row exists; only the
		# DocType-level create grant governs who may create one at all.
		return True
	student_name = (
		_nba_operational_student(doc)
		if doc.doctype in {"CRM Action Execution", "CRM Action Outcome", "CRM Recommendation Feedback"}
		else None
	)
	if student_name is None:
		student_field = OPERATIONAL_RECORD_STUDENT_FIELDS.get(doc.doctype)
		student_name = doc.get(student_field) if student_field else None
	if not student_name:
		return False
	student = frappe.get_doc("CRM Student", student_name)
	return has_permission(student, user=user, permission_type=permission_type)


def _nba_operational_permission_query_conditions(*, user=None, doctype):
	student_condition = get_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	if student_condition == "1=0":
		return "1=0"
	rec_table = f"{chr(96)}tabCRM Recommendation{chr(96)}"
	student_names = (
		f"select {rec_table}.name from {rec_table} "
		f"where {rec_table}.target_type = 'CRM Student' and {rec_table}.target_id in ("
		f"select {chr(96)}tabCRM Student{chr(96)}.name from {chr(96)}tabCRM Student{chr(96)} "
		f"where ({student_condition}))"
	)
	table = f"{chr(96)}tab{doctype}{chr(96)}"
	if doctype == "CRM Action Execution":
		return f"{table}.recommendation in ({student_names})"
	if doctype == "CRM Action Outcome":
		execution_table = f"{chr(96)}tabCRM Action Execution{chr(96)}"
		return f"{table}.execution in (select {execution_table}.name from {execution_table} where {execution_table}.recommendation in ({student_names}))"
	if doctype == "CRM Recommendation Feedback":
		return f"{table}.recommendation in ({student_names})"
	return "1=0"


def _nba_operational_student(doc):
	if doc.doctype == "CRM Action Execution":
		recommendation = doc.get("recommendation")
	elif doc.doctype == "CRM Action Outcome":
		execution = doc.get("execution")
		recommendation = (
			frappe.db.get_value("CRM Action Execution", execution, "recommendation") if execution else None
		)
	else:
		recommendation = doc.get("recommendation")
	if not recommendation:
		return None
	target_type, target_id = frappe.db.get_value(
		"CRM Recommendation", recommendation, ["target_type", "target_id"]
	) or (None, None)
	return target_id if target_type == "CRM Student" else None


def get_permission_query_conditions(doctype, user=None):
	if not user:
		user = frappe.session.user
	if user == frappe.conf.get("crm_agents_service_user") and doctype in {
		"CRM Student",
		"CRM Intent Type",
	}:
		# The configured crm-agents identity is a service capability, not a
		# human CRM profile. Its scope is constrained at the named command
		# boundary and must be able to read bounded analysis inputs/catalogues.
		return None

	roles = set(_get_policy_roles(user))
	if user == "Administrator" or "System Manager" in roles:
		return None
	scope = _effective_case_scope(roles, doctype, user=user)
	# CRM Lead and CRM Student are independent aggregates, so both always use
	# the same authoritative scope policy. Conversion history is not a
	# permission boundary for standalone Student records.
	if scope == "all":
		return None
	if scope == "deny":
		return "1=0"

	crm_staff_name = _get_crm_staff_name(user)
	if not crm_staff_name:
		return "1=0"

	table = f"`tab{doctype}`"

	if frappe.conf.get("crm_legacy_campus_scoping"):
		# The optional campus fallback never widens Sale/CTV Sale beyond their
		# own-assigned-only rule even when this flag
		# is set, so flipping it can't silently widen their visibility.
		if scope in {"assigned", "own_assigned"}:
			return f"{table}.assigned_to = {frappe.db.escape(crm_staff_name)}"
		if scope in {"campus_assigned", "campus_assigned_contact"}:
			return _campus_condition(table, crm_staff_name)
		return _team_leader_condition(table, crm_staff_name)

	if scope in {"team_and_team_pool", "team_members_and_own_team_pool"}:
		team_condition = _team_leader_condition(table, crm_staff_name)
		# Lead Sale must be able to see every Lead that has not been assigned
		# yet. Intake is owned by another system, so an unassigned Lead may not
		# have owning_team populated and cannot be discovered through the old
		# team-pool condition alone. Keep the existing team scope as well so
		# already-routed records remain visible to their team leader.
		if doctype == "CRM Lead":
			unassigned_condition = f"({table}.owner_staff is null and {table}.assigned_to is null)"
			return f"({unassigned_condition} or {team_condition})"
		return team_condition

	if scope in {"campus_assigned", "campus_assigned_contact"}:
		return _campus_condition(table, crm_staff_name)

	if scope in {"assigned", "own_assigned"}:
		return f"{table}.owner_staff = {frappe.db.escape(crm_staff_name)}"

	return "1=0"


def can_read_full_lead_board(user=None) -> bool:
	"""Whether this profile keeps full-board compatibility for Lead detail/write.

	Lead Sale routes Leads into every province's Team, so the board it works
	from must keep allowing detail and routing writes after a batch commits
	ownership to a Sale on another Team. The LeadList API applies the explicit
	Group/Team scope separately, so this compatibility flag no longer widens
	list visibility.

	The flag still aligns the Lead Sale write check with detail access; Student,
	delete, and every assignment, conversion, ownership, or lifecycle command keep
	their existing checks.
	"""
	user = user or frappe.session.user
	return resolve_crm_profile(_get_policy_roles(user)) == "lead_sales"


def can_write_full_lead_board(user=None) -> bool:
	"""Whether a Lead Sale may edit any Lead shown on the intake board.

	Lead Sale is the intake/routing operator. Detail and routing writes retain the
	full-board compatibility scope, while LeadList itself is Group/Team scoped.
	This exception is limited to CRM Lead writes; Student, read, delete, and
	ownership/lifecycle command permissions keep their existing checks.
	"""
	return can_read_full_lead_board(user)


def get_student_list_read_condition(user=None, *, doctype="CRM Student"):
	"""Return the list-only Student read scope for roles with assignment access.

	Sale keeps the canonical assigned-only row scope for direct CRUD and detail
	operations, but the student list must expose the Sale's team and team pool so
	the user can choose a target for an ownership assignment. The assignment
	command still enforces its own authorization and ownership revision checks.

	Lead Sale additionally sees assigned Students in active Teams belonging to
	active Groups led by the current CRM Staff. This is the existing Student
	dashboard scope, not a new endpoint or a new UI flow.

	Other profiles return ``None`` so callers continue using the canonical
	permission query hook unchanged. ``doctype`` identifies the aggregate being
	queried by the caller; the default remains the standalone CRM Student table,
	while the dashboard projection may target CRM Lead.
	"""
	table_by_doctype = {
		"CRM Student": "`tabCRM Student`",
		"CRM Lead": "`tabCRM Lead`",
	}
	table = table_by_doctype[doctype]
	user = user or frappe.session.user
	profile = resolve_crm_profile(_get_policy_roles(user))
	if profile == "lead_sales":
		crm_staff_name = _get_crm_staff_name(user)
		if not crm_staff_name:
			return "1=0"
		return _lead_sales_student_read_condition(table, crm_staff_name, doctype=doctype)
	if profile != "sales":
		return None

	crm_staff_name = _get_crm_staff_name(user)
	if not crm_staff_name:
		return "1=0"

	own_condition = f"{table}.owner_staff = {frappe.db.escape(crm_staff_name)}"
	team_condition = _team_leader_condition(table, crm_staff_name)
	return f"({own_condition} or {team_condition})"


def has_student_dashboard_read_permission(doc, user=None):
	"""Check existing Student dashboard/detail visibility for Lead Sale.

	This helper is deliberately separate from ``has_student_list_read_permission``
	because the latter is also used by ownership commands. The Group-level
	visibility is therefore not accidentally reused as a mutation grant.
	"""
	user = user or frappe.session.user
	if resolve_crm_profile(_get_policy_roles(user)) != "lead_sales":
		return bool(doc.has_permission("read"))

	condition = get_student_list_read_condition(user)
	if condition == "1=0" or not getattr(doc, "name", None):
		return False
	return bool(
		frappe.db.sql(
			f"select name from `tabCRM Student` where name = %s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def has_student_list_read_permission(doc, user=None):
	"""Check the Student read scope used by list-and-assign flows.

	For ordinary Student CRUD/detail access, callers must continue using
	``has_permission``. Sale's assignment flow is the one deliberate exception:
	it may inspect a Student in its own team or pool before assigning it.
	"""
	condition = get_student_list_read_condition(user)
	if condition is None:
		return has_permission(doc, user=user, permission_type="read")
	if condition == "1=0" or not getattr(doc, "name", None):
		return False
	return bool(
		frappe.db.sql(
			f"select name from `tabCRM Student` where name = %s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def get_interaction_permission_query_conditions(user=None, doctype=None):
	"""Row-level scope for CRM Interaction: Student-linked or Contact-only.

	A CRM Interaction has no independent row scope of its own -- before this
	hook, its DocType-level role grants (e.g. Sale, Marketing) were the only
	access check, so any role with a channel-based read grant could see every
	student's interactions regardless of assignment.  This always derives from
	the same Student/Contact scope as CRM Lead/CRM Student: never from
	channel, interaction_type, or role alone. A pre-conversion (student is
	null) interaction falls back to the linked CRM Student's scope.
	"""
	if doctype != "CRM Interaction":
		return "1=0"
	user = user or frappe.session.user
	student_condition = get_permission_query_conditions("CRM Student", user=user)
	contact_condition = get_permission_query_conditions("CRM Student", user=user)
	table = "`tabCRM Interaction`"

	def _student_clause():
		if student_condition is None:
			return f"{table}.student is not null"
		if student_condition == "1=0":
			return None
		return (
			f"{table}.student in (select `tabCRM Student`.name from `tabCRM Student` "
			f"where ({student_condition}))"
		)

	def _contact_clause():
		if contact_condition is None:
			return f"{table}.student is null and {table}.crm_contact is not null"
		if contact_condition == "1=0":
			return None
		return (
			f"{table}.student is null and {table}.crm_contact in "
			f"(select `tabCRM Student`.name from `tabCRM Student` where ({contact_condition}))"
		)

	if student_condition is None and contact_condition is None:
		return None
	parts = [clause for clause in (_student_clause(), _contact_clause()) if clause]
	if not parts:
		return "1=0"
	return "(" + " or ".join(parts) + ")"


def _has_interaction_create_permission(doc, user=None) -> bool:
	"""Check the unsaved Interaction's *target* scope, not its own row.

	Unlike a name-keyed row-scope query (which needs doc.name and so cannot
	run before insert -- see has_operational_record_permission's docstring),
	the linked Student/Contact already exists and its scope can be checked
	directly from the unsaved doc's link fields. A DocType-level create grant
	(e.g. Sale) must never bypass this -- otherwise any role with that grant
	could attach an interaction to a student/contact outside their scope.
	"""
	if doc.get("student"):
		student = frappe.db.exists("CRM Student", doc.student)
		if not student:
			return False
		return has_permission(frappe.get_doc("CRM Student", doc.student), user=user)
	if doc.get("crm_contact"):
		contact = frappe.db.exists("CRM Student", doc.crm_contact)
		if not contact:
			return False
		return has_permission(frappe.get_doc("CRM Student", doc.crm_contact), user=user)
	# Neither target is set -- nothing to scope against; deny rather than
	# silently allow an orphaned interaction to bypass row scope.
	return False


def has_interaction_permission(doc, user=None, permission_type=None, ptype=None):
	# Accepts both ptype and permission_type -- see has_operational_record_
	# permission's docstring: frappe.call only forwards the kwarg name(s) a
	# hook function actually declares, and the real hook call uses `ptype`.
	permission_type = permission_type or ptype
	if permission_type == "create":
		return _has_interaction_create_permission(doc, user=user)
	condition = get_interaction_permission_query_conditions(user=user, doctype="CRM Interaction")
	if condition is None:
		return True
	if condition == "1=0":
		return False
	table = "`tabCRM Interaction`"
	return bool(
		frappe.db.sql(
			f"select name from {table} where name = %s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def get_intent_permission_query_conditions(user=None, doctype=None):
	"""Row-level scope for CRM Intent: derived from its parent Interaction.

	CRM Intent.student is read_only and copied from its (required) `interaction`
	link's student (crm_intent.py's before_validate), so it is null for a
	Contact-only, pre-conversion interaction. Reusing the generic Student-scope
	operational-record condition would wrongly deny every Intent on such an
	interaction. Instead this joins through `interaction` and reuses that
	doctype's own Student/Contact fallback scope directly.
	"""
	if doctype != "CRM Intent":
		return "1=0"
	interaction_condition = get_interaction_permission_query_conditions(user=user, doctype="CRM Interaction")
	if interaction_condition is None:
		return None
	if interaction_condition == "1=0":
		return "1=0"
	return (
		"`tabCRM Intent`.interaction in (select `tabCRM Interaction`.name "
		f"from `tabCRM Interaction` where ({interaction_condition}))"
	)


def _has_intent_create_permission(doc, user=None) -> bool:
	"""Check the unsaved Intent's linked Interaction scope, not its own row.

	`interaction` is `reqd=1` on CRM Intent, so it is always present on an
	unsaved doc. A DocType-level create grant must not bypass this -- it
	would otherwise let a role attach an intent to an interaction outside
	their scope.
	"""
	interaction_name = doc.get("interaction")
	if not interaction_name:
		return False
	interaction = frappe.db.exists("CRM Interaction", interaction_name)
	if not interaction:
		return False
	return has_interaction_permission(frappe.get_doc("CRM Interaction", interaction_name), user=user)


def has_intent_permission(doc, user=None, permission_type=None, ptype=None):
	# See has_operational_record_permission's docstring for why both kwarg
	# names are accepted.
	permission_type = permission_type or ptype
	if permission_type == "create":
		return _has_intent_create_permission(doc, user=user)
	condition = get_intent_permission_query_conditions(user=user, doctype="CRM Intent")
	if condition is None:
		return True
	if condition == "1=0":
		return False
	table = "`tabCRM Intent`"
	return bool(
		frappe.db.sql(
			f"select name from {table} where name = %s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def get_student_projection_permission_query_conditions(user=None, doctype=None):
	"""Scope Student-linked projections through the canonical Student policy.

	AI Insight and Agent Event are projections, not independent authorization
	roots.  Their DocType role grants only describe who may use the projection;
	the linked Student scope remains the source of truth. Events whose aggregate
	is a Student-bearing operational record are joined back to that Student.
	Global events (for example scoring-policy changes) remain unavailable through
	the row-scoped event stream instead of becoming an unscoped side channel.
	"""
	if doctype not in {"CRM AI Lead Insight", "CRM Agent Event"}:
		return "1=0"
	user = user or frappe.session.user
	student_condition = get_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	if student_condition == "1=0":
		return "1=0"
	student_names = f"select `tabCRM Student`.name from `tabCRM Student` where ({student_condition})"
	if doctype == "CRM AI Lead Insight":
		return f"`tabCRM AI Lead Insight`.student in ({student_names})"
	return (
		"(`tabCRM Agent Event`.aggregate_doctype = 'CRM Student' and "
		f"`tabCRM Agent Event`.aggregate_name in ({student_names})) OR "
		"(`tabCRM Agent Event`.aggregate_doctype = 'CRM Action Item' and "
		"`tabCRM Agent Event`.aggregate_name in (select action_scope.name "
		"from `tabCRM Action Item` action_scope where action_scope.student in "
		f"({student_names}))) OR "
		"(`tabCRM Agent Event`.aggregate_doctype = 'CRM Student Decision Event' and "
		"`tabCRM Agent Event`.aggregate_name in (select decision_scope.name "
		"from `tabCRM Student Decision Event` decision_scope where decision_scope.student in "
		f"({student_names})))"
	)


def has_student_projection_permission(doc, user=None, permission_type=None, ptype=None):
	"""Apply the Student row scope to single projection records as well."""
	permission_type = permission_type or ptype
	if permission_type == "create" and not getattr(doc, "name", None):
		student_name = doc.get("student") if doc.doctype == "CRM AI Lead Insight" else None
		if doc.doctype == "CRM Agent Event" and doc.get("aggregate_doctype") == "CRM Student":
			student_name = doc.get("aggregate_name")
		if not student_name:
			return False
		if not frappe.db.exists("CRM Student", student_name):
			return False
		return has_permission(frappe.get_doc("CRM Student", student_name), user=user)
	condition = get_student_projection_permission_query_conditions(user=user, doctype=doc.doctype)
	if condition is None:
		return True
	if condition == "1=0":
		return False
	return bool(
		frappe.db.sql(
			f"select name from `tab{doc.doctype}` where name = %s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def get_admission_decision_permission_query_conditions(user=None, doctype=None):
	if doctype != "CRM Admission Event Decision":
		return "1=0"
	student_condition = get_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	return f"`tabCRM Admission Event Decision`.student in (select `tabCRM Student`.name from `tabCRM Student` where ({student_condition}))"


def has_admission_decision_permission(doc, user=None, permission_type=None, ptype=None):
	if (permission_type or ptype) == "create":
		return False
	condition = get_admission_decision_permission_query_conditions(user=user, doctype=doc.doctype)
	if condition is None:
		return True
	return bool(
		frappe.db.sql(
			f"select name from `tabCRM Admission Event Decision` where name=%s and ({condition}) limit 1",
			(doc.name,),
		)
	)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	"""Single-document counterpart of get_permission_query_conditions.

	permission_query_conditions only filters list/report-view SQL — Frappe never
	consults it for frappe.get_doc, the desk single-record view, or the REST API's
	GET /api/resource/<doctype>/<name>. Without this hook a scoped-out user could
	still read/write any record directly by name, defeating the locked BR matrix.
	"""
	if not user:
		user = frappe.session.user
	# Frappe passes the requested permission as ``ptype`` to hook methods.  A
	# new document has no database name yet, so applying a name-keyed row-scope
	# query would both be meaningless and deny otherwise valid create grants.
	# The regular DocType permission check remains responsible for deciding who
	# may create; this hook scopes existing rows only.
	permission_type = permission_type or ptype
	if permission_type == "create" and not getattr(doc, "name", None):
		return True
	if permission_type == "write" and doc.doctype == "CRM Lead" and can_write_full_lead_board(user):
		return True

	condition = get_permission_query_conditions(doc.doctype, user=user)
	if condition == "1=0":
		return False
	if condition is not None:
		table = f"`tab{doc.doctype}`"
		in_scope = bool(
			frappe.db.sql(
				f"select name from {table} where name = %s and ({condition}) limit 1",
				(doc.name,),
			)
		)
		if not in_scope:
			return False

	if permission_type == "delete" and _delete_requires_ownership(user):
		return _user_owns_or_is_assigned_to(doc, user)
	return True


def _effective_case_scope(roles, doctype, *, user):
	"""Delegate policy selection; this module only turns a scope into SQL."""
	return case_scope_for_roles(roles, doctype, administrator=user == "Administrator")


def _delete_requires_ownership(user):
	roles = set(_get_policy_roles(user))
	return delete_requires_ownership_for_roles(roles, administrator=user == "Administrator")


def _get_policy_roles(user=None):
	"""Return the role set used by both session and row-scope authorization.

	Frappe omits an explicitly assigned ``Administrator`` role from its raw role
	list for normal users.  The session contract restores that role so it can
	represent the CRM CEO profile; row-level permission checks must use the same
	normalized role set or CEO accounts are denied despite their DocPerm grant.
	"""
	from crm.api.session import _get_policy_roles as get_policy_roles

	return get_policy_roles(user)


def _user_owns_or_is_assigned_to(doc, user):
	"""PRD P0-3: delete only if owner (creator) OR assigned_to, checked in
	addition to -- never instead of -- the row-scope check already passed by
	the caller. `assigned_to` is a CRM Staff link (kept equal to `owner_staff`
	by derive_owner_fields), so it is compared against the acting user's own
	CRM Staff record, not their User name.
	"""
	if doc.get("owner") == user:
		return True
	crm_staff_name = _get_crm_staff_name(user)
	return bool(crm_staff_name) and doc.get("assigned_to") == crm_staff_name


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
	"""Compute (owner_staff, owning_team) for an *assigned* CRM Student/Student.
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

	# Unassigned-pool: Contact/Student now carry owning_team directly, so
	# this is an exact match against the leader's own team(s) — no more approximating
	# team ownership via a shared campus, which used to risk leaking a sibling team's
	# unassigned records (constraint 3).
	team_clause = _in_clause(f"{table}.owning_team", teams)
	if team_clause:
		parts.append(f"({table}.owner_staff is null and {team_clause})")

	if not parts:
		return "1=0"
	return "(" + " or ".join(parts) + ")"


def _lead_sales_student_read_condition(table, crm_staff_name, *, doctype="CRM Student"):
	"""Add Group-level Team and pool visibility to the existing Team scope."""
	parts = []
	team_condition = _team_leader_condition(table, crm_staff_name)
	if team_condition != "1=0":
		parts.append(team_condition)

	group_ids = _get_groups_led_by_staff(crm_staff_name)
	if group_ids:
		teams = frappe.get_all(
			"CRM Team",
			filters={"group": ["in", group_ids], "is_active": 1},
			pluck="name",
		)
		if teams:
			team_parts = []
			team_clause = _in_clause(f"{table}.owning_team", teams)
			if team_clause:
				team_parts.append(team_clause)
			staff_in_teams = frappe.get_all(
				"CRM Team Membership",
				filters={"team": ["in", teams], "parenttype": "CRM Staff"},
				pluck="parent",
			)
			staff_clause = _in_clause(f"{table}.owner_staff", staff_in_teams)
			if staff_clause:
				team_parts.append(staff_clause)
			if team_parts:
				assigned_clause = (
					f"{table}.owner_staff is not null and {table}.assigned_to is not null"
				)
				parts.append(f"({assigned_clause} and ({' or '.join(team_parts)}))")
			if team_clause:
				parts.append(
					f"({table}.owner_staff is null and {table}.assigned_to is null and {team_clause})"
				)

			# Lead intake without a Team is still visible to the Group Lead when
			# its province belongs to one of the managed Groups. Student rows keep
			# their existing converted/assigned invariant in the API filters.
			if doctype == "CRM Lead":
				group_provinces = frappe.get_all(
					"CRM Team Group",
					filters={"name": ["in", group_ids], "is_active": 1},
					pluck="province",
				)
				province_clause = _in_clause(f"{table}.province", group_provinces)
				if province_clause:
					parts.append(
						f"({table}.owner_staff is null and {table}.assigned_to is null and "
						f"{province_clause})"
					)

	if not parts:
		return "1=0"
	return "(" + " or ".join(parts) + ")"


def _get_groups_led_by_staff(crm_staff_name):
	return _cached(
		f"crm_staff_led_groups::{crm_staff_name}",
		lambda: frappe.get_all(
			"CRM Team Group",
			filters={"group_lead_staff": crm_staff_name, "is_active": 1},
			pluck="name",
		),
	)


def _campus_condition(table, crm_staff_name):
	campus = frappe.db.get_value("CRM Staff", crm_staff_name, "campus")
	if not campus:
		return "1=0"

	staff_in_campus = frappe.get_all("CRM Staff", filters={"campus": campus}, pluck="name")
	clause = _in_clause(f"{table}.owner_staff", staff_in_campus)
	return clause or "1=0"
