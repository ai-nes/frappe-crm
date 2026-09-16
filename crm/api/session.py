import frappe
from frappe import _
from frappe.utils import getdate, today

from crm.api._pagination import parse_pagination
from crm.fcrm.role_policy import (
	ADMINISTRATOR_ROLE,
	CRM_BUSINESS_ROLES,
	POLICY_VERSION,
	PROFILE_LABELS,
	PROFILE_ROLE_ALIASES,
	capabilities_for_roles,
	capability_details,
	classify_role_set,
	is_crm_user,
)
from crm.fcrm.role_policy import (
	resolve_crm_profile as _resolve_crm_profile,
)
from crm.fcrm.student_feature_flags import director_analytics_read_enabled, role_workspace_read_enabled

# Compatibility exports for existing API consumers. New consumers import the
# canonical policy module rather than adding role literals here.
CRM_ROLE_PROFILES = PROFILE_ROLE_ALIASES
CRM_PROFILE_LABELS = PROFILE_LABELS
USER_FIELDS = [
	"name",
	"email",
	"enabled",
	"user_image",
	"first_name",
	"last_name",
	"full_name",
	"user_type",
	"language",
]
CRM_USER_ROLE_NAMES = tuple(sorted(CRM_BUSINESS_ROLES | {ADMINISTRATOR_ROLE, "System Manager"}))


def resolve_crm_profile(roles):
	"""Return the sole canonical business profile, otherwise ``None``.

	Roles from two profiles are intentionally indistinguishable from an
	unmapped caller: both fail closed rather than making declaration order a
	persona selection policy.
	"""
	return _resolve_crm_profile(roles)


def resolve_copilot_profile(roles):
	"""Return a Copilot profile while keeping System Manager control-plane-only.

	The demo full-access switch (`crm_agents_demo_full_access` site_config,
	shared with the mutation/discovery demo paths) also assigns a fixed demo
	profile to System Manager/Administrator, so one bare Administrator login
	can drive Copilot without seeding a canonical operating-role account.
	"""
	role_names = frozenset(roles)
	if "System Manager" in role_names:
		if frappe.conf.get("crm_agents_demo_full_access") in (1, "1", True, "true", "True"):
			return "Admissions Director"
		return None
	profile = resolve_crm_profile(role_names)
	label = CRM_PROFILE_LABELS.get(profile, profile)
	# crm-agents requires the published profile to be one of the server-issued
	# role names. Same-domain legacy aliases remain valid Desk identities but do
	# not silently acquire a different Copilot persona.
	return label if label in role_names else None


def get_crm_user_role(roles):
	"""Return the UI role label and profile for a User's actual Frappe roles."""
	role_names = frozenset(roles)
	role_state = classify_role_set(role_names)
	profile = resolve_crm_profile(role_names)
	if role_state == "canonical_profile" and profile:
		return CRM_PROFILE_LABELS[profile], profile
	if role_state == "system_manager":
		return "System Manager", None
	if role_names & CRM_BUSINESS_ROLES:
		return "", None
	return "", None


def _crm_feature_flags(profile):
	"""Return rollout state that the SPA may use for progressive enhancement.

	Director analytics is intentionally not advertised to other CRM profiles or
	platform administrators.  Server-side workspace authorization remains the
	security boundary; this only prevents the client from rendering a canary
	entry it cannot use.
	"""
	return {
		"role_workspace_read": role_workspace_read_enabled(),
		"director_analytics_read": profile == "admissions_director" and director_analytics_read_enabled(),
	}


def _session_role_flags(roles):
	"""Build flags from server-derived roles; shared with focused contract tests."""
	role_names = frozenset(roles)
	profile = resolve_crm_profile(role_names)
	role_state = classify_role_set(role_names)
	if role_state in {"legacy_migration_required", "mixed_or_unmapped", "unmapped"}:
		frappe.throw(_("Your CRM business roles are ambiguous or unsupported."), frappe.PermissionError)
	if not is_crm_user(role_names):
		frappe.throw(_("You are not permitted to access CRM resources."), frappe.PermissionError)
	capabilities = sorted(capabilities_for_roles(role_names))

	# Keep the legacy booleans stable for older SPA callers, while mapping them
	# to the canonical Sale / Lead Sale profiles.
	return {
		"is_system_manager": bool({"System Manager", ADMINISTRATOR_ROLE} & role_names),
		"is_sales_manager": profile == "lead_sales" and "System Manager" not in role_names,
		"is_sales_user": profile == "sales" and "System Manager" not in role_names,
		"is_crm_user": is_crm_user(role_names),
		"crm_profile": profile,
		# Compatibility field consumed by the local crm-agents gateway.
		"crm_role": CRM_PROFILE_LABELS.get(profile, profile),
		"crm_role_state": role_state,
		"crm_capabilities": capabilities,
		"crm_capability_details": capability_details(capabilities),
		"crm_policy_version": POLICY_VERSION,
		"crm_feature_flags": _crm_feature_flags(profile),
	}


def _get_my_team_memberships(user=None):
	"""Return the current user's business role and role inside each Team.

	``CRM Staff.team_memberships.function`` is the business function (Sale,
	CTV Sale, or Lead Sale).  ``CRM Team.team_lead_staff`` is the source of
	truth for the organisational role, so the same person can be a Lead Sale
	and a Team member in one Team or a Sale and a Team lead in another.
	"""
	user = user or frappe.session.user
	staff_id = frappe.db.get_value("CRM Staff", {"user": user}, "name")
	if not staff_id:
		return []

	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"parent": staff_id, "parenttype": "CRM Staff"},
		fields=[
			"name",
			"team",
			"function",
			"term",
			"effective_from",
			"effective_until",
			"is_primary",
		],
		order_by="is_primary desc, team asc, name asc",
		limit_page_length=0,
	)

	today_date = getdate(today())
	active_memberships = [
		row
		for row in memberships
		if (not row.effective_from or getdate(row.effective_from) <= today_date)
		and (not row.effective_until or getdate(row.effective_until) >= today_date)
	]
	team_ids = sorted({row.team for row in active_memberships if row.team})
	if not team_ids:
		return []

	teams = frappe.get_all(
		"CRM Team",
		filters={"name": ["in", team_ids], "is_active": 1},
		fields=["name", "team_name", "group", "team_lead_staff"],
		limit_page_length=0,
	)
	team_map = {row.name: row for row in teams}
	group_ids = sorted({row.group for row in teams if row.group})
	groups = (
		frappe.get_all(
			"CRM Team Group",
			filters={"name": ["in", group_ids], "is_active": 1},
			fields=["name", "group_name", "province"],
			limit_page_length=0,
		)
		if group_ids
		else []
	)
	group_map = {row.name: row for row in groups}

	result = []
	for membership in active_memberships:
		team = team_map.get(membership.team)
		if not team:
			continue
		group = group_map.get(team.group)
		is_team_lead = team.team_lead_staff == staff_id
		result.append(
			{
				"id": membership.name,
				"team_id": team.name,
				"team_name": team.team_name or team.name,
				"group_id": group.name if group else None,
				"group_name": group.group_name if group else None,
				"province_id": group.province if group else None,
				"role": membership.function,
				"function": membership.function,
				"membership_role": "Trưởng nhóm" if is_team_lead else "Thành viên",
				"team_role": "team_lead" if is_team_lead else "member",
				"is_team_lead": is_team_lead,
				"is_primary": bool(membership.is_primary),
				"term": membership.term or None,
			}
		)
	return result


def _get_my_managed_group_members(user=None):
	"""Return members in Groups where the current user leads at least one Team."""
	user = user or frappe.session.user
	staff_id = frappe.db.get_value("CRM Staff", {"user": user}, "name")
	if not staff_id:
		return []

	led_teams = frappe.get_all(
		"CRM Team",
		filters={"team_lead_staff": staff_id, "is_active": 1},
		fields=["name", "team_name", "group", "team_lead_staff"],
		limit_page_length=0,
	)
	group_ids = sorted({row.group for row in led_teams if row.group})
	if not group_ids:
		return []

	groups = frappe.get_all(
		"CRM Team Group",
		filters={"name": ["in", group_ids], "is_active": 1},
		fields=["name", "group_name", "province"],
		limit_page_length=0,
	)
	group_map = {row.name: row for row in groups}
	managed_group_ids = set(group_map)
	if not managed_group_ids:
		return []

	teams = frappe.get_all(
		"CRM Team",
		filters={"group": ["in", list(managed_group_ids)], "is_active": 1},
		fields=["name", "team_name", "group", "team_lead_staff"],
		limit_page_length=0,
	)
	team_map = {row.name: row for row in teams}
	team_ids = sorted(team_map)
	if not team_ids:
		return []

	memberships = frappe.get_all(
		"CRM Team Membership",
		filters={"team": ["in", team_ids], "parenttype": "CRM Staff"},
		fields=[
			"name",
			"parent as staff",
			"team",
			"function",
			"term",
			"effective_from",
			"effective_until",
			"is_primary",
		],
		limit_page_length=0,
	)
	today_date = getdate(today())
	active_memberships = [
		row
		for row in memberships
		if (not row.effective_from or getdate(row.effective_from) <= today_date)
		and (not row.effective_until or getdate(row.effective_until) >= today_date)
	]
	staff_ids = sorted({row.staff for row in active_memberships if row.staff})
	staff_rows = (
		frappe.get_all(
			"CRM Staff",
			filters={"name": ["in", staff_ids], "is_active": 1},
			fields=["name", "full_name", "user"],
			limit_page_length=0,
		)
		if staff_ids
		else []
	)
	staff_map = {row.name: row for row in staff_rows}

	result = []
	for membership in active_memberships:
		staff = staff_map.get(membership.staff)
		team = team_map.get(membership.team)
		if not staff or not team:
			continue
		group = group_map.get(team.group)
		is_team_lead = team.team_lead_staff == staff.name
		result.append(
			{
				"id": membership.name,
				"staff_id": staff.name,
				"full_name": staff.full_name or staff.name,
				"email": staff.user,
				"team_id": team.name,
				"team_name": team.team_name or team.name,
				"group_id": group.name,
				"group_name": group.group_name,
				"province_id": group.province,
				"role": membership.function,
				"function": membership.function,
				"membership_role": "Trưởng nhóm" if is_team_lead else "Thành viên",
				"team_role": "team_lead" if is_team_lead else "member",
				"is_team_lead": is_team_lead,
				"is_primary": bool(membership.is_primary),
			}
		)
	return result


def _get_policy_roles(user=None):
	"""Return Frappe roles plus an explicitly assigned Administrator profile.

	Frappe filters ``Administrator`` from ``frappe.get_roles`` for every user
	except the technical Administrator account because it is an automatic role.
	CRM exposes Administrator as a canonical selectable profile, so preserve an
	explicit assignment for the CRM policy layer.
	"""
	user = user or frappe.session.user
	roles = list(frappe.get_roles(user))
	if (
		user != "Administrator"
		and ADMINISTRATOR_ROLE not in roles
		and frappe.db.exists(
			"Has Role",
			{"parent": user, "parenttype": "User", "role": ADMINISTRATOR_ROLE},
		)
	):
		roles.append(ADMINISTRATOR_ROLE)
	return roles


def get_session_role_flags():
	# Frappe auto-grants every Role in the system to the "Administrator" account.
	# Keep the explicit Administrator branch because it is a platform superuser,
	# not a normal System Manager control-plane account — mirrors the Administrator bypass in
	# crm.api.check_app_permission.
	if frappe.session.user == "Administrator":
		return {
			"is_system_manager": True,
			"is_sales_manager": False,
			"is_sales_user": False,
			"is_crm_user": True,
			"crm_profile": None,
			"crm_role": None,
			"crm_role_state": "platform_superuser",
			"crm_capabilities": sorted(capabilities_for_roles(set(), administrator=True)),
			"crm_capability_details": capability_details(capabilities_for_roles(set(), administrator=True)),
			"crm_policy_version": POLICY_VERSION,
			"crm_feature_flags": _crm_feature_flags(None),
		}
	return _session_role_flags(_get_policy_roles())


@frappe.whitelist()
def get_my_roles():
	"""Return the roles of the CURRENT session user (bound by the auth token
	on this request), never a caller-supplied username. Frappe's token/bearer
	auth already resolves `frappe.session.user` from the credential presented
	on this request before this function runs, so there is no lookup-on-behalf-of
	step here — a caller can only ever learn their own roles.

	Consumed by crm-agents (the internal chat copilot) to gate access to the
	sales/marketing ReAct surface without a service account inferring identity
	from client-supplied input.
	"""
	flags = get_session_role_flags()
	return {
		"user": frappe.session.user,
		"roles": _get_policy_roles(),
		"crm_profile": flags["crm_profile"],
		"crm_role": flags["crm_role"],
		"crm_role_state": flags["crm_role_state"],
		"crm_capabilities": flags["crm_capabilities"],
		"crm_capability_details": flags["crm_capability_details"],
		"crm_policy_version": flags["crm_policy_version"],
		"crm_feature_flags": flags["crm_feature_flags"],
	}


@frappe.whitelist(allow_guest=True)
def me():
	"""Identity for an external SPA (the admissions dashboard) served cross-origin.

	Returns ``{"user": None}`` for an unauthenticated session instead of raising,
	so the client can treat "logged out" as a normal state and route to /login.
	An authenticated non-CRM user still fails closed via ``get_session_role_flags``.
	"""
	if frappe.session.user == "Guest":
		return {"user": None, "permission": []}

	flags = get_session_role_flags()
	user = frappe.db.get_value(
		"User",
		frappe.session.user,
		["name", "email", "full_name", "user_image"],
		as_dict=True,
	)
	return {
		"user": user.name,
		"email": user.email,
		"full_name": user.full_name,
		"user_image": user.user_image,
		"roles": _get_policy_roles(),
		"crm_profile": flags["crm_profile"],
		"crm_role": flags["crm_role"],
		"crm_capabilities": flags["crm_capabilities"],
		"crm_capability_details": flags["crm_capability_details"],
		"permission": flags["crm_capabilities"],
		"permission_details": flags["crm_capability_details"],
		"crm_team_memberships": _get_my_team_memberships(),
		"crm_managed_group_members": _get_my_managed_group_members(),
		# The cross-origin SPA has no server-rendered page to read frappe.boot
		# from, so hand it the CSRF token it must send as `X-Frappe-CSRF-Token`
		# on write requests (production enforces CSRF; dev sets ignore_csrf).
		"csrf_token": _csrf_token(),
	}


def _csrf_token() -> str | None:
	try:
		from frappe.sessions import get_csrf_token

		return get_csrf_token()
	except Exception:
		return None


def _decorate_user(user, session_roles, system_language):
	if frappe.session.user == user.name:
		user.session_user = True
		user.crm_feature_flags = session_roles["crm_feature_flags"]

	user.roles = _get_policy_roles(user.name)

	if user.name == "Administrator":
		# Same blanket-role-grant issue as get_session_role_flags(): Administrator
		# holds every role, which trips get_crm_user_role()'s ambiguous-profile
		# fail-closed check and would otherwise drop it from crm_users below.
		user.role, user.crm_profile = "System Manager", None
		user.crm_role = None
		user.crm_role_state = "platform_superuser"
		user.crm_capabilities = sorted(capabilities_for_roles(set(), administrator=True))
	else:
		user.role, user.crm_profile = get_crm_user_role(user.roles)
		user.crm_role = CRM_PROFILE_LABELS.get(user.crm_profile, user.crm_profile)
		user.crm_role_state = classify_role_set(user.roles)
		user.crm_capabilities = sorted(capabilities_for_roles(user.roles))
	if not user.role and "Guest" in user.roles:
		user.role = "Guest"

	user.is_telephony_agent = frappe.db.exists("Telephony Agent", {"user": user.name})
	user.language = user.language or system_language or "vi"
	return is_crm_user(user.roles, administrator=user.name == "Administrator")


@frappe.whitelist()
def get_users():
	session_roles = get_session_role_flags()

	users = frappe.qb.get_query(
		"User",
		fields=USER_FIELDS,
		order_by="full_name asc",
		distinct=True,
		filters={"enabled": 1},
	).run(as_dict=1)

	crm_users = []
	system_language = frappe.db.get_single_value("System Settings", "language") or "vi"

	for user in users:
		if _decorate_user(user, session_roles, system_language):
			crm_users.append(user)

	if not session_roles["is_system_manager"]:
		users = crm_users

	return users, crm_users


@frappe.whitelist()
def list_admin_users(
	start: int | str = 0,
	page_length: int | str = 20,
	search: str | None = None,
	role: str | None = None,
) -> dict:
	"""Return one permission-scoped page for the Admin user-management table."""
	session_roles = get_session_role_flags()
	if not session_roles["is_system_manager"]:
		frappe.throw(_("Only System Managers may list all CRM users."), frappe.PermissionError)

	start, page_length = parse_pagination(start, page_length)

	crm_user_names = frappe.get_all(
		"Has Role",
		filters={
			"parenttype": "User",
			"role": ["in", list(CRM_USER_ROLE_NAMES)],
		},
		pluck="parent",
		limit_page_length=0,
	)
	crm_user_names = [name for name in crm_user_names if name != "Administrator"]
	filters = {"enabled": 1, "name": ["in", crm_user_names]}

	if role and role != "all":
		role_users = frappe.get_all(
			"Has Role",
			filters={"parenttype": "User", "role": role},
			pluck="parent",
			limit_page_length=0,
		)
		filters["name"] = ["in", sorted(set(crm_user_names).intersection(role_users))]

	search_value = str(search or "").strip()
	or_filters = None
	if search_value:
		like = f"%{search_value}%"
		or_filters = [[fieldname, "like", like] for fieldname in ("name", "email", "full_name")]

	users = frappe.get_list(
		"User",
		fields=USER_FIELDS,
		filters=filters,
		or_filters=or_filters,
		order_by="full_name asc, name asc",
		start=start,
		page_length=page_length,
	)
	count_rows = frappe.get_list(
		"User",
		filters=filters,
		or_filters=or_filters,
		fields=["count(name) as total"],
		limit_page_length=0,
	)
	total = int((count_rows[0].get("total") if count_rows else 0) or 0)
	system_language = frappe.db.get_single_value("System Settings", "language") or "vi"
	for user in users:
		_decorate_user(user, session_roles, system_language)

	return {
		"users": users,
		"total": total,
		"start": start,
		"page_length": page_length,
	}


def set_default_user_language(doc, event=None):
	"""Ensure user records default to Vietnamese ('vi') if no language is specified."""
	if not doc.language:
		doc.language = "vi"


def set_default_crm_app_for_sales(doc, event=None):
	"""Send Sales users to the CRM application after sign-in by default."""
	if doc.default_app:
		return
	roles = {row.role for row in doc.get("roles", [])}
	if roles & {"Sale", "CTV Sale", "Lead Sale"}:
		doc.default_app = "crm"


@frappe.whitelist()
def get_high_schools():
	get_session_role_flags()

	high_schools = frappe.qb.get_query(
		"CRM High School",
		fields=["*"],
		order_by="name asc",
		distinct=True,
	).run(as_dict=1)

	return high_schools
