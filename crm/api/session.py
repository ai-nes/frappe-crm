import frappe
from frappe import _

CRM_BUSINESS_ROLES = frozenset({"Sale", "Lead Sales", "Marketing", "Admissions Director"})
CRM_ALLOWED_ROLES = frozenset({"System Manager"}) | CRM_BUSINESS_ROLES


def resolve_crm_profile(roles):
	"""Return the one assigned canonical business role, otherwise ``None``.

	There are no compatibility aliases: a role assignment is authoritative only
	when it contains exactly one of the four CRM business roles.
	"""
	matches = frozenset(roles) & CRM_BUSINESS_ROLES
	return next(iter(matches)) if len(matches) == 1 else None


def resolve_copilot_profile(roles):
	"""Return a business Copilot profile, denying System Manager absolutely.

	System Manager is an AI-exposure control-plane role. It must never acquire
	a Copilot persona through a coexisting legacy business alias during the
	canonical-role migration.
	"""
	role_names = frozenset(roles)
	if "System Manager" in role_names:
		return None
	return resolve_crm_profile(role_names)


def get_crm_user_role(roles):
	"""Return the UI role label and profile for a User's actual Frappe roles."""
	role_names = frozenset(roles)
	if "System Manager" in role_names:
		# Keep the control-plane identity visible in the UI and prevent a
		# coexisting legacy business alias from selecting a Copilot persona.
		return "System Manager", None
	profile = resolve_crm_profile(role_names)
	if profile:
		return profile, profile
	if role_names & CRM_BUSINESS_ROLES:
		# Non-System users with business roles from multiple canonical profiles
		# are ambiguous and must remove/migrate the extra aliases first.
		return "", None
	return "", None


def _session_role_flags(roles):
	"""Build flags from server-derived roles; shared with focused contract tests."""
	role_names = frozenset(roles)
	is_system_manager = "System Manager" in role_names
	profile = resolve_copilot_profile(role_names)
	if not is_system_manager and role_names & CRM_BUSINESS_ROLES and profile is None:
		frappe.throw(_("Your CRM business roles are ambiguous or unsupported."), frappe.PermissionError)
	if not profile and not is_system_manager:
		frappe.throw(_("You are not permitted to access CRM resources."), frappe.PermissionError)

	return {
		"is_system_manager": is_system_manager,
		"is_crm_user": bool(profile) or is_system_manager,
		"crm_role": profile,
	}


def get_session_role_flags():
	return _session_role_flags(frappe.get_roles())


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
	return {"user": frappe.session.user, "roles": frappe.get_roles(), "crm_role": flags["crm_role"]}


@frappe.whitelist()
def get_users():
	session_roles = get_session_role_flags()

	users = frappe.qb.get_query(
		"User",
		fields=[
			"name",
			"email",
			"enabled",
			"user_image",
			"first_name",
			"last_name",
			"full_name",
			"user_type",
			"language",
		],
		order_by="full_name asc",
		distinct=True,
		filters={"enabled": 1},
	).run(as_dict=1)

	crm_users = []
	system_language = frappe.db.get_single_value("System Settings", "language")

	for user in users:
		if frappe.session.user == user.name:
			user.session_user = True

		user.roles = frappe.get_roles(user.name)

		user.role, user.crm_role = get_crm_user_role(user.roles)
		if not user.role and "Guest" in user.roles:
			user.role = "Guest"

		if frappe.session.user == user.name:
			user.session_user = True

		user.is_telephony_agent = frappe.db.exists("Telephony Agent", {"user": user.name})
		user.language = user.language or system_language

		if user.crm_role or user.role == "System Manager":
			crm_users.append(user)

	if not session_roles["is_system_manager"]:
		users = crm_users

	return users, crm_users


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
