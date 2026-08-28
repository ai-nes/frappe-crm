import frappe
from frappe import _

from crm.fcrm.role_policy import (
	CRM_BUSINESS_ROLES,
	LEGACY_COMPATIBILITY_OVERLAYS,
	POLICY_VERSION,
	PROFILE_LABELS,
	PROFILE_ROLE_ALIASES,
	capabilities_for_roles,
	classify_role_set,
	is_crm_user,
	resolve_compatibility_overlay,
)
from crm.fcrm.role_policy import (
	resolve_crm_profile as _resolve_crm_profile,
)

# Compatibility exports for existing API consumers. New consumers import the
# canonical policy module rather than adding role literals here.
CRM_ROLE_PROFILES = PROFILE_ROLE_ALIASES
CRM_PROFILE_LABELS = PROFILE_LABELS


def resolve_crm_profile(roles):
	"""Return the sole canonical business profile, otherwise ``None``.

	A person can keep several migration aliases for the same profile.  Roles
	from two profiles are intentionally indistinguishable from an unmapped
	caller: both fail closed rather than making declaration order a persona
	selection policy.
	"""
	return _resolve_crm_profile(roles)


def resolve_copilot_profile(roles):
	"""Return a Copilot profile while keeping System Manager control-plane-only."""
	role_names = frozenset(roles)
	if "System Manager" in role_names:
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
	overlay = resolve_compatibility_overlay(role_names)
	if role_state == "compatibility_overlay" and overlay:
		legacy_roles = role_names & LEGACY_COMPATIBILITY_OVERLAYS[overlay]["roles"]
		return sorted(legacy_roles)[0], None
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

	# Keep the legacy booleans stable for older SPA callers, while mapping them
	# to the canonical Sale / Lead Sales profiles.
	return {
		"is_system_manager": "System Manager" in role_names,
		"is_sales_manager": profile == "lead_sales" and "System Manager" not in role_names,
		"is_sales_user": profile == "sales" and "System Manager" not in role_names,
		"is_crm_user": is_crm_user(role_names),
		"crm_profile": profile,
		# Compatibility field consumed by the local crm-agents gateway.
		"crm_role": CRM_PROFILE_LABELS.get(profile, profile),
		"crm_role_state": role_state,
		"crm_capabilities": sorted(capabilities_for_roles(role_names)),
		"crm_policy_version": POLICY_VERSION,
		"crm_feature_flags": _crm_feature_flags(profile),
	}


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
			"crm_policy_version": POLICY_VERSION,
			"crm_feature_flags": _crm_feature_flags(None),
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
	return {
		"user": frappe.session.user,
		"roles": frappe.get_roles(),
		"crm_profile": flags["crm_profile"],
		"crm_role": flags["crm_role"],
		"crm_role_state": flags["crm_role_state"],
		"crm_capabilities": flags["crm_capabilities"],
		"crm_policy_version": flags["crm_policy_version"],
		"crm_feature_flags": flags["crm_feature_flags"],
	}


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
	system_language = frappe.db.get_single_value("System Settings", "language") or "vi"

	for user in users:
		if frappe.session.user == user.name:
			user.session_user = True
			user.crm_feature_flags = session_roles["crm_feature_flags"]

		user.roles = frappe.get_roles(user.name)

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

		if frappe.session.user == user.name:
			user.session_user = True

		user.is_telephony_agent = frappe.db.exists("Telephony Agent", {"user": user.name})
		user.language = user.language or system_language or "vi"

		if is_crm_user(user.roles, administrator=user.name == "Administrator"):
			crm_users.append(user)

	if not session_roles["is_system_manager"]:
		users = crm_users

	return users, crm_users


def set_default_user_language(doc, event=None):
	"""Ensure user records default to Vietnamese ('vi') if no language is specified."""
	if not doc.language:
		doc.language = "vi"


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
