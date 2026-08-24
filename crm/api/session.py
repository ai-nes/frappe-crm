import frappe
from frappe import _

CRM_ROLE_PROFILES = {
	# Sales Manager/User are retained as migration aliases. They deliberately
	# select the Sales persona only; they do not grant manager permissions.
	"sales": frozenset({"Sale", "CTV-Sale", "Counseller", "Sales Manager", "Sales User"}),
	"marketing": frozenset({"Marketing", "Promoter-PR"}),
	"lead_sales": frozenset({"Team Leader", "Lead Sales"}),
	"admissions_director": frozenset({"Admissions Director", "Giám đốc Tuyển sinh"}),
}
CRM_PROFILE_LABELS = {
	"sales": "Sales",
	"marketing": "Marketing",
	"lead_sales": "Lead Sales",
	"admissions_director": "Admissions Director",
}
CRM_BUSINESS_ROLES = frozenset().union(*CRM_ROLE_PROFILES.values())
CRM_ALLOWED_ROLES = frozenset({"System Manager"}) | CRM_BUSINESS_ROLES


def resolve_crm_profile(roles):
	"""Return the sole canonical business profile, otherwise ``None``.

	A person can keep several migration aliases for the same profile.  Roles
	from two profiles are intentionally indistinguishable from an unmapped
	caller: both fail closed rather than making declaration order a persona
	selection policy.
	"""
	role_names = frozenset(roles)
	matches = [profile for profile, aliases in CRM_ROLE_PROFILES.items() if role_names & aliases]
	return matches[0] if len(matches) == 1 else None


def get_crm_user_role(roles):
	"""Return the UI role label and profile for a User's actual Frappe roles."""
	role_names = frozenset(roles)
	profile = resolve_crm_profile(role_names)
	if profile:
		return CRM_PROFILE_LABELS[profile], profile
	if role_names & CRM_BUSINESS_ROLES:
		# A System Manager must not mask a conflicting business-role set.  The
		# caller must first remove/migrate the extra profile aliases.
		return "", None
	if "System Manager" in role_names:
		return "System Manager", None
	return "", None


def _session_role_flags(roles):
	"""Build flags from server-derived roles; shared with focused contract tests."""
	role_names = frozenset(roles)
	profile = resolve_crm_profile(role_names)
	if role_names & CRM_BUSINESS_ROLES and profile is None:
		frappe.throw(_("Your CRM business roles are ambiguous or unsupported."), frappe.PermissionError)
	if not profile and "System Manager" not in role_names:
		frappe.throw(_("You are not permitted to access CRM resources."), frappe.PermissionError)

	# Keep the legacy booleans stable for older SPA callers. New consumers must
	# use crm_profile/is_crm_user so a Marketing or Lead Sales account never
	# masquerades as a Sales Manager/User.
	return {
		"is_system_manager": "System Manager" in role_names,
		"is_sales_manager": "Sales Manager" in role_names and "System Manager" not in role_names,
		"is_sales_user": (
			"Sales User" in role_names
			and "Sales Manager" not in role_names
			and "System Manager" not in role_names
		),
		"is_crm_user": bool(profile) or "System Manager" in role_names,
		"crm_profile": profile,
	}


def get_session_role_flags():
	# Frappe auto-grants every Role in the system to the "Administrator" account,
	# so it always trips the mixed-business-profile fail-closed check below. That
	# check exists to catch real users with conflicting role assignments, not the
	# framework superuser — mirrors the Administrator bypass in
	# crm.api.check_app_permission.
	if frappe.session.user == "Administrator":
		return {
			"is_system_manager": True,
			"is_sales_manager": False,
			"is_sales_user": False,
			"is_crm_user": True,
			"crm_profile": None,
		}
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
	return {"user": frappe.session.user, "roles": frappe.get_roles(), "crm_profile": flags["crm_profile"]}


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

		user.role, user.crm_profile = get_crm_user_role(user.roles)
		if not user.role and "Guest" in user.roles:
			user.role = "Guest"

		if frappe.session.user == user.name:
			user.session_user = True

		user.is_telephony_agent = frappe.db.exists("Telephony Agent", {"user": user.name})
		user.language = user.language or system_language

		if user.crm_profile or user.role == "System Manager":
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
