"""Canonical CRM role/profile policy.

This module resolves *identity and capabilities* only. DocPerm, row scope, and
workflow commands consume it in later Phase 2 slices; none of them may invent a
second role catalog. `CRM Data Steward` is intentionally not a profile or a
capability source.
"""

from __future__ import annotations

POLICY_VERSION = "phase2-v1"
SYSTEM_MANAGER_ROLE = "System Manager"

PROFILE_LABELS = {
	"sales": "Sale",
	"marketing": "Marketing",
	"lead_sales": "Lead Sales",
	"admissions_director": "Admissions Director",
}

PROFILE_ROLE_ALIASES = {
	"sales": frozenset({"Sale"}),
	"marketing": frozenset({"Marketing"}),
	"lead_sales": frozenset({"Lead Sales"}),
	"admissions_director": frozenset({"Admissions Director"}),
}

PROFILE_CAPABILITIES = {
	"sales": frozenset({"student.execute", "interaction.record", "outcome.record"}),
	"marketing": frozenset({"acquisition.manage", "attribution.manage"}),
	"lead_sales": frozenset(
		{
			"student.execute",
			"interaction.record",
			"outcome.record",
			"team.oversee",
			"team.pool.read",
			"student.ownership.manage",
		}
	),
	"admissions_director": frozenset(
		{
			"admissions.oversee",
			"lifecycle.exception",
			"student.ownership.manage",
			"student.audit.reason.read",
		}
	),
}

CANONICAL_SELECTABLE_ROLES = frozenset({SYSTEM_MANAGER_ROLE, *PROFILE_LABELS.values()})

_PERMISSION_FLAGS = {
	"r": "read",
	"w": "write",
	"c": "create",
	"d": "delete",
	"x": "export",
}

# DocPerm vocabulary is deliberately kept separate from Frappe's raw permission
# dictionaries. Phase 2.2 is the only consumer allowed to translate this contract
# into database records. The values below mirror the reviewed Phase 2 matrix:
# r=read, w=write, c=create, d=delete, x=export; "-" means no grant.
CANONICAL_PERMISSION_MATRIX = {
	"admissions_case": {
		"doctypes": ("CRM Student", "CRM Contact"),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "rwc",
			"lead_sales": "rwc",
			"marketing": "-",
			"admissions_director": "rx",
		},
		"row_scope": {
			"sales": "assigned",
			"lead_sales": "team_and_team_pool",
			"admissions_director": "all",
			"default": "deny",
		},
	},
	"reference": {
		"doctypes": (
			"CRM Major",
			"CRM Major Group",
			"CRM High School",
			"CRM Province",
			"CRM Ward",
			"CRM Region",
			"CRM School Type",
			"CRM Aspiration",
			"CRM Enrollment Status",
			"CRM Admission Year",
			"CRM Education Program",
			"CRM Campaign Type",
			"CRM Department",
			"Holiday List",
			"CRM Team",
		),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "r",
			"lead_sales": "r",
			"marketing": "r",
			"admissions_director": "rx",
		},
		"row_scope": "none",
	},
	"acquisition": {
		"doctypes": ("CRM Campaign", "CRM Event"),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "r",
			"lead_sales": "r",
			"marketing": "rwcdx",
			"admissions_director": "rx",
		},
		"row_scope": "marketing_owned_record",
	},
	"governed_acquisition": {
		"doctypes": ("CRM Lead Source", "CRM Platform", "CRM Intent Type"),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "r",
			"lead_sales": "r",
			"marketing": "rwc",
			"admissions_director": "r",
		},
		"row_scope": "marketing_governed_mutation",
	},
	"governed_admissions": {
		"doctypes": ("CRM Lost Reason", "CRM Campus"),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "r",
			"lead_sales": "r",
			"marketing": "r",
			"admissions_director": "r",
		},
		"per_doctype_permissions": {
			"CRM Lost Reason": {"lead_sales": "rwc"},
			"CRM Campus": {"admissions_director": "rwc"},
		},
		"row_scope": "campus_is_not_team_scope",
	},
	"control_plane": {
		"doctypes": (
			"Fields Layout",
			"Form Script",
			"View Settings",
			"Global Settings",
			"FCRM Settings",
			"Notification",
			"Dashboard",
			"Invitation",
			"Telephony Agent",
			"Service Level Agreement",
			"CRM Influence",
			"CRM Academic Year Config",
		),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "-",
			"lead_sales": "-",
			"marketing": "-",
			"admissions_director": "-",
		},
		"row_scope": "system_only",
	},
	"legacy_untouched": {
		"doctypes": (
			"CRM Staff",
			"CRM Person",
			"Task",
			"Call Log",
			"FCRM Note",
			"CRM Score Template",
			"CRM Score History",
			"CRM Recommendation",
			"CRM Sales Action",
		),
		"permissions": {
			"system_manager": "unchanged",
			"sales": "unchanged",
			"lead_sales": "unchanged",
			"marketing": "unchanged",
			"admissions_director": "unchanged",
		},
		"row_scope": "legacy_untouched",
	},
}

# These records preserve legacy scope in Phase 2.2 without elevating a user to
# a canonical profile. A role set can select at most one overlay; the selector
# will fail closed rather than union separate historic grants.
LEGACY_COMPATIBILITY_OVERLAYS = {
	"sales_own": {
		"roles": frozenset({"CTV-Sale", "Sales User"}),
		"case_permissions": "rwc",
		"reference_permissions": "r",
		"acquisition_permissions": "r",
		"governed_acquisition_permissions": "r",
		"governed_admissions_permissions": "r",
		"control_permissions": "-",
		"row_scope": "own_assigned",
	},
	"counseller_campus": {
		"roles": frozenset({"Counseller"}),
		"case_permissions": "rwc",
		"reference_permissions": "r",
		"acquisition_permissions": "r",
		"governed_acquisition_permissions": "r",
		"governed_admissions_permissions": "r",
		"control_permissions": "-",
		"row_scope": "campus_assigned",
	},
	"team_leader": {
		"roles": frozenset({"Sales Manager", "Team Leader"}),
		"case_permissions": "rwcdx",
		"reference_permissions": "rx",
		"acquisition_permissions": "rwcdx",
		"governed_acquisition_permissions": "r",
		"governed_admissions_permissions": "r",
		"control_permissions": "-",
		"row_scope": "team_members_and_own_team_pool",
	},
	"promoter_campus": {
		"roles": frozenset({"Promoter-PR"}),
		"case_permissions": {"CRM Student": "-", "CRM Contact": "r"},
		"reference_permissions": "r",
		"acquisition_permissions": "r",
		"governed_acquisition_permissions": "r",
		"governed_admissions_permissions": "r",
		"control_permissions": "-",
		"row_scope": "campus_assigned_contact",
	},
	"marketing_operator": {
		"roles": frozenset({"Marketing Operator"}),
		"case_permissions": "-",
		"reference_permissions": "r",
		"acquisition_permissions": "rwcdx",
		"governed_acquisition_permissions": "rwc",
		"governed_admissions_permissions": "r",
		"control_permissions": "-",
		"row_scope": "no_case_scope",
	},
	"marketing_lead": {
		"roles": frozenset({"Marketing Lead"}),
		"case_permissions": "-",
		"reference_permissions": "r",
		"acquisition_permissions": "rwc",
		"governed_acquisition_permissions": "r",
		"governed_admissions_permissions": "r",
		"control_permissions": "-",
		"row_scope": "no_case_scope",
	},
	"admissions_operations": {
		"roles": frozenset({"Admissions Operations"}),
		"case_permissions": "rwc",
		"reference_permissions": "r",
		"acquisition_permissions": "r",
		"governed_acquisition_permissions": "r",
		"governed_admissions_permissions": "rwc",
		"control_permissions": "-",
		"row_scope": "all_cases",
	},
	"admissions_director_legacy": {
		"roles": frozenset({"Giám đốc Tuyển sinh"}),
		"case_permissions": "rx",
		"reference_permissions": "rx",
		"acquisition_permissions": "rx",
		"governed_acquisition_permissions": "r",
		"governed_admissions_permissions": "r",
		"control_permissions": "-",
		"row_scope": "all_cases",
	},
}

# Each source is retired only by the forward backfill migration below. The
# resolver deliberately rejects accounts holding sources for multiple targets;
# a migration must never guess a person's operating role.
ROLE_BACKFILL_TARGETS = {
	"CTV-Sale": "Sale",
	"Counseller": "Sale",
	"Sales User": "Sale",
	"Sales Manager": "Lead Sales",
	"Team Leader": "Lead Sales",
	"Promoter-PR": "Marketing",
	"Marketing Operator": "Marketing",
	"Marketing Lead": "Marketing",
	"Admissions Operations": "Admissions Director",
	"Giám đốc Tuyển sinh": "Admissions Director",
}
ROLE_BACKFILL_SOURCES = frozenset(ROLE_BACKFILL_TARGETS)

# These roles exist in some databases from pre-Phase-2 models. They are
# explicit migration findings, never overlays and never permission sources.
# ``Sales`` is the retired duplicate of canonical ``Sale``; new users must not
# receive it and existing assignments must be migrated explicitly.
LEGACY_UNMAPPED_ROLES = frozenset({"CRM Data Steward", "Sales"})

SYSTEM_MANAGER_CAPABILITIES = frozenset({"system.configure", "roles.manage", "system.recover"})
LEGACY_OVERLAY_IDS = frozenset(LEGACY_COMPATIBILITY_OVERLAYS)
LEGACY_OVERLAY_ROLES = frozenset().union(
	*(LEGACY_COMPATIBILITY_OVERLAYS[overlay]["roles"] for overlay in LEGACY_OVERLAY_IDS)
)
CANONICAL_PROFILE_ROLES = frozenset().union(*PROFILE_ROLE_ALIASES.values())
CRM_POLICY_ROLE_NAMES = tuple(
	sorted(CANONICAL_SELECTABLE_ROLES | CANONICAL_PROFILE_ROLES | LEGACY_OVERLAY_ROLES | ROLE_BACKFILL_SOURCES)
)
CRM_BUSINESS_ROLES = CANONICAL_PROFILE_ROLES | LEGACY_OVERLAY_ROLES | ROLE_BACKFILL_SOURCES
CRM_ALLOWED_ROLES = frozenset(
	{
		SYSTEM_MANAGER_ROLE,
		"Sale",
		"CTV-Sale",
		"Counseller",
		"Sales Manager",
		"Sales User",
		"Marketing",
		"Promoter-PR",
		"Marketing Operator",
		"Marketing Lead",
		"Team Leader",
		"Lead Sales",
		"Admissions Director",
		"Admissions Operations",
		"Giám đốc Tuyển sinh",
	}
)
FRAMEWORK_ROLE_NAMES = frozenset({"All", "Guest", "Desk User", "Website User"})

# A number of pre-Phase-2 accounts carry both an operating sales alias and a
# sales-lead alias.  These roles describe one sales domain, so they have one
# deterministic canonical outcome instead of a union of the two legacy
# templates.  Keep the set intentionally narrow: roles from another business
# domain must continue to fail closed.
_SALES_OPERATOR_COMPATIBILITY_ROLES = frozenset({"Sale", "Sales User"})
_SALES_LEAD_COMPATIBILITY_ROLES = frozenset({"Sales Manager", "Team Leader"})
_SALES_COMPATIBILITY_ROLES = (
	_SALES_OPERATOR_COMPATIBILITY_ROLES | _SALES_LEAD_COMPATIBILITY_ROLES
)


def _unknown_role_names(role_names):
	"""Return role names outside the policy and Frappe's implicit roles."""
	return role_names - CRM_ALLOWED_ROLES - FRAMEWORK_ROLE_NAMES - LEGACY_UNMAPPED_ROLES


def resolve_crm_profile(roles) -> str | None:
	"""Return one canonical profile using deterministic same-domain precedence.

	System Manager is a control-plane role and therefore never resolves to an
	operating profile.  A sales lead alias combined with a sales operator alias
	resolves to ``lead_sales``; capabilities are taken from that profile only,
	never unioned from both legacy role templates.
	"""
	role_names = frozenset(roles)
	if (
		_unknown_role_names(role_names)
		or role_names & LEGACY_UNMAPPED_ROLES
		or SYSTEM_MANAGER_ROLE in role_names
	):
		return None
	if role_names & LEGACY_OVERLAY_ROLES:
		if (
			role_names & _SALES_OPERATOR_COMPATIBILITY_ROLES
			and role_names & _SALES_LEAD_COMPATIBILITY_ROLES
			and not role_names - _SALES_COMPATIBILITY_ROLES - FRAMEWORK_ROLE_NAMES
		):
			return "lead_sales"
		return None
	matches = [profile for profile, aliases in PROFILE_ROLE_ALIASES.items() if role_names & aliases]
	return matches[0] if len(matches) == 1 else None


def resolve_compatibility_overlay(roles) -> str | None:
	"""Return one retained legacy template, or None for absent/ambiguous input."""
	role_names = frozenset(roles)
	if _unknown_role_names(role_names) or role_names & (
		CANONICAL_PROFILE_ROLES | {SYSTEM_MANAGER_ROLE} | LEGACY_UNMAPPED_ROLES
	):
		return None
	matches = [
		overlay
		for overlay in LEGACY_OVERLAY_IDS
		for template in (LEGACY_COMPATIBILITY_OVERLAYS[overlay],)
		if role_names & template["roles"]
	]
	return matches[0] if len(matches) == 1 else None


def backfill_target_for_roles(roles) -> str | None:
	"""Return one explicit migration target, never an inferred mixed profile."""
	targets = {ROLE_BACKFILL_TARGETS[role] for role in frozenset(roles) & ROLE_BACKFILL_SOURCES}
	return next(iter(targets)) if len(targets) == 1 else None


def classify_role_set(roles, *, administrator=False) -> str:
	"""Classify a role set for migration diagnostics without granting authority."""
	if administrator:
		return "platform_superuser"

	role_names = frozenset(roles)
	if role_names & LEGACY_UNMAPPED_ROLES:
		return "legacy_migration_required"
	unknown_roles = _unknown_role_names(role_names)
	if unknown_roles:
		known_business_roles = role_names & (CANONICAL_PROFILE_ROLES | LEGACY_OVERLAY_ROLES | {SYSTEM_MANAGER_ROLE})
		return "mixed_or_unmapped" if known_business_roles else "unmapped"
	# System Manager owns the control plane.  Accidental or transitional
	# operating-role assignments must not add operating capabilities, but also
	# must not lock the account out of CRM administration.
	if SYSTEM_MANAGER_ROLE in role_names:
		return "system_manager"

	profile = resolve_crm_profile(role_names)
	overlay = resolve_compatibility_overlay(role_names)
	if (
		(role_names & CANONICAL_PROFILE_ROLES and profile is None)
		or (profile and overlay)
		or (role_names & LEGACY_OVERLAY_ROLES and overlay is None and profile is None)
	):
		return "mixed_or_unmapped"
	if profile:
		return "canonical_profile"
	if overlay:
		return "compatibility_overlay"
	if SYSTEM_MANAGER_ROLE in role_names:
		return "system_manager"
	return "unmapped"


def capabilities_for_roles(roles, *, administrator=False) -> frozenset[str]:
	"""Return policy capabilities without treating legacy data roles as authority."""
	role_names = frozenset(roles)
	if administrator:
		return SYSTEM_MANAGER_CAPABILITIES
	classification = classify_role_set(role_names)
	if classification in {"legacy_migration_required", "mixed_or_unmapped", "unmapped"}:
		return frozenset()
	profile = resolve_crm_profile(role_names)
	if SYSTEM_MANAGER_ROLE in role_names:
		return SYSTEM_MANAGER_CAPABILITIES
	return PROFILE_CAPABILITIES.get(profile, frozenset())


def is_crm_user(roles, *, administrator=False) -> bool:
	if administrator:
		return True
	return classify_role_set(roles) in {"canonical_profile", "compatibility_overlay", "system_manager"}


def case_scope_for_roles(roles, doctype, *, administrator=False):
	"""Resolve the sole Student/Contact scope from the canonical policy data."""
	if administrator:
		return "all"
	role_names = frozenset(roles)
	role_state = classify_role_set(role_names)
	if role_state == "system_manager":
		return "all"
	if role_state == "canonical_profile":
		profile = resolve_crm_profile(role_names)
		return CANONICAL_PERMISSION_MATRIX["admissions_case"]["row_scope"].get(profile, "deny")
	if role_state != "compatibility_overlay":
		return "deny"

	overlay = resolve_compatibility_overlay(role_names)
	if not overlay:
		return "deny"
	scope = LEGACY_COMPATIBILITY_OVERLAYS[overlay]["row_scope"]
	if scope == "campus_assigned_contact" and doctype != "CRM Contact":
		return "deny"
	if scope == "all_cases":
		return "all"
	return scope


def managed_docperm_rows():
	"""Translate the versioned policy matrix into managed Frappe DocPerm rows.

	The result deliberately excludes `legacy_untouched` surfaces. Callers must
	leave those existing rows alone rather than allowing a future fall-through
	grant to regenerate them.
	"""
	rows_by_doctype = {}
	for surface, definition in CANONICAL_PERMISSION_MATRIX.items():
		if surface == "legacy_untouched":
			continue
		for doctype in definition["doctypes"]:
			rows = []
			for profile, permission_set in definition["permissions"].items():
				permission_set = definition.get("per_doctype_permissions", {}).get(doctype, {}).get(
					profile, permission_set
				)
				role = SYSTEM_MANAGER_ROLE if profile == "system_manager" else PROFILE_LABELS[profile]
				row = _docperm_row(role, permission_set)
				if row:
					rows.append(row)
			for overlay in LEGACY_OVERLAY_IDS:
				template = LEGACY_COMPATIBILITY_OVERLAYS[overlay]
				permission_set = _overlay_permission_set(surface, template, doctype)
				for role in template["roles"]:
					row = _docperm_row(role, permission_set)
					if row:
						rows.append(row)
			rows_by_doctype[doctype] = sorted(rows, key=lambda row: row["role"])
	return rows_by_doctype


def _overlay_permission_set(surface, template, doctype):
	if surface == "admissions_case":
		permission_set = template["case_permissions"]
		return permission_set.get(doctype, "-") if isinstance(permission_set, dict) else permission_set
	key = {
		"reference": "reference_permissions",
		"acquisition": "acquisition_permissions",
		"governed_acquisition": "governed_acquisition_permissions",
		"governed_admissions": "governed_admissions_permissions",
		"control_plane": "control_permissions",
	}[surface]
	return template[key]


def _docperm_row(role, permission_set):
	if permission_set in {"-", "unchanged"}:
		return None
	if permission_set == "same":
		raise ValueError("Canonical aliases must resolve through a canonical profile")
	return {"role": role, **{field: 1 for verb, field in _PERMISSION_FLAGS.items() if verb in permission_set}}
