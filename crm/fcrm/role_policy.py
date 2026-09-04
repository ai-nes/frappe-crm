"""Canonical CRM role/profile policy.

This module resolves *identity and capabilities* only. DocPerm, row scope, and
workflow commands consume it in later Phase 2 slices; none of them may invent a
second role catalog. `CRM Data Steward` is intentionally not a profile or a
capability source.
"""

from __future__ import annotations

POLICY_VERSION = "phase2-v1"
SYSTEM_MANAGER_ROLE = "System Manager"
DESK_MANAGEMENT_ROLE_NAMES = (
	"Workspace Manager",
	"Dashboard Manager",
	"Report Manager",
)

PROFILE_LABELS = {
	"sales": "Sale",
	"marketing": "Marketing",
	"lead_sales": "Lead Sales",
	"admissions_director": "Admissions Director",
	# PRD-phan-quyen-lead.md roles (2026-09-04). Unlike the profiles above,
	# these are not derived from `CANONICAL_PERMISSION_MATRIX` -- their
	# `CRM Permission Profile` rows are hand-transcribed from the PRD by
	# `crm.patches.v1_0.seed_new_lead_role_profiles`, and they carry no
	# `PROFILE_CAPABILITIES` (the PRD scopes them to plain Lead CRUD, none of
	# the recommendation/lifecycle actions the other profiles gate).
	# "PR (nhân viên)" reuses the pre-existing "Promoter" role name rather
	# than introducing a new "PR" role (explicit product decision, 2026-09-04)
	# -- `Promoter` is therefore split out of `marketing`'s aliases below into
	# its own profile with the PRD's distinct CRUD.
	# Department-head roles use the "Lead <Department>" naming already
	# established by "Lead Sales" (explicit product decision, 2026-09-04).
	"ctv_sale": "CTV Sale",
	"pr": "Promoter",
	"pr_manager": "Lead Promoter",
	"lead_marketing": "Lead Marketing",
	"ceo": "CEO",
}

# Phase 9 removes raw Desk/API/import writes for governed lookups.  Creation,
# retirement and supersession are exposed only through master_data_governance.
PHASE9_COMMAND_ONLY_DOCTYPES = frozenset({"CRM Lead Source", "CRM Platform", "CRM Term", "CRM Campus"})

PROFILE_ROLE_ALIASES = {
	"sales": frozenset({"Sale"}),
	# "Promoter" moved out to its own "pr" profile below (2026-09-04) -- it no
	# longer shares Marketing's permissions, it gets the PRD's PR CRUD.
	"marketing": frozenset({"Marketing"}),
	"lead_sales": frozenset({"Lead Sales"}),
	"admissions_director": frozenset({"Admissions Director"}),
	"ctv_sale": frozenset({"CTV Sale"}),
	"pr": frozenset({"Promoter"}),
	"pr_manager": frozenset({"Lead Promoter"}),
	"lead_marketing": frozenset({"Lead Marketing"}),
	"ceo": frozenset({"CEO"}),
}

PROFILE_CAPABILITIES = {
	"sales": frozenset(
		{
			"student.execute",
			"conversion.execute",
			"recommendation.decide",
			"action.execute",
			"interaction.record",
			"outcome.record",
			"lifecycle.transition",
			"lifecycle.lost",
			"student.routing.read",
			"student.sla.read",
			"student.sla.respond",
		}
	),
	"marketing": frozenset({
		"acquisition.manage", "attribution.manage", "school.activity.manage", "school.person.manage",
	}),
	"lead_sales": frozenset(
		{
			"student.execute",
			"conversion.execute",
			"recommendation.decide",
			"action.execute",
			"action.reassign",
			"interaction.record",
			"outcome.record",
			"lifecycle.transition",
			"lifecycle.lost",
			"lifecycle.reopen",
			"team.oversee",
			"team.pool.read",
			"student.ownership.manage",
			"student.routing.read",
			"student.routing.operate",
			"student.routing.retry",
			"student.sla.read",
			"student.sla.operate",
			"student.sla.pause",
			"student.sla.reset.request",
			"student.sla.escalation.read",
		}
	),
	"admissions_director": frozenset(
		{
			"admissions.oversee",
			"conversion.execute",
			"recommendation.decide",
			"action.execute",
			"action.reassign",
			"lifecycle.exception",
			"lifecycle.transition",
			"lifecycle.lost",
			"lifecycle.reopen",
			"student.ownership.manage",
			"student.audit.reason.read",
			"student.routing.read",
			"student.routing.operate",
			"student.routing.retry",
			"student.sla.read",
			"student.sla.operate",
			"student.sla.pause",
			"student.sla.escalation.read",
			"student.sla.reset.approve",
			"student.policy.approve",
		}
	),
}

CANONICAL_SELECTABLE_ROLES = frozenset({SYSTEM_MANAGER_ROLE, *PROFILE_LABELS.values(), *PROFILE_ROLE_ALIASES["marketing"]})

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
	"attribution_evidence": {
		"doctypes": ("CRM Marketing Engagement",),
		"permissions": {
			"system_manager": "r",
			"sales": "-",
			"lead_sales": "-",
			"marketing": "-",
			"admissions_director": "-",
		},
		"row_scope": "student_context_or_redacted_endpoint",
	},
	"admissions_case": {
		"doctypes": ("CRM Student", "CRM Contact"),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "rwc",
			# PRD-phan-quyen-lead.md P0-1 (2026-09-04): Trưởng phòng Sale (Lead
			# Sales) gets conditional delete, gated by this profile's existing
			# `delete_requires_ownership=1` -- no unconditional bulk delete.
			"lead_sales": "rwcd",
			# PRD-phan-quyen-lead.md P0-1 (2026-09-04): Marketing/Trưởng phòng
			# Marketing need read-only visibility for channel-performance
			# analysis; still campus-scoped per P0-2, see row_scope below.
			"marketing": "r",
			"admissions_director": "rx",
		},
		"row_scope": {
			"sales": "assigned",
			"lead_sales": "team_and_team_pool",
			"admissions_director": "all",
			"marketing": "campus_assigned",
			"default": "deny",
		},
	},
	"reference": {
		"doctypes": (
			"CRM Major", "CRM Term", "CRM High School", "CRM Province", "CRM Ward",
			"CRM Admission Year",
			"CRM Education Program",
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
		"doctypes": ("CRM Lead Source", "CRM Platform", "CRM Term"),
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
		"doctypes": ("CRM Term", "CRM Campus"),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "r",
			"lead_sales": "r",
			"marketing": "r",
			"admissions_director": "r",
		},
		"per_doctype_permissions": {
			"CRM Term": {"lead_sales": "rwc"},
			"CRM Campus": {"admissions_director": "rwc"},
		},
		"row_scope": "campus_is_not_team_scope",
	},
	"decision_action": {
		"doctypes": ("CRM Recommendation", "CRM Action", "CRM Action Item", "CRM Student Decision Event"),
		"permissions": {
			"system_manager": "rwcdx",
			"sales": "r",
			"lead_sales": "r",
			"marketing": "-",
			"admissions_director": "r",
		},
		"row_scope": {
			"sales": "assigned",
			"lead_sales": "team_and_team_pool",
			"admissions_director": "all",
			"default": "deny",
		},
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
		"attribution_evidence_permissions": "-",
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
		"attribution_evidence_permissions": "-",
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
		"attribution_evidence_permissions": "-",
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
		"attribution_evidence_permissions": "-",
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
		"attribution_evidence_permissions": "-",
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
		"attribution_evidence_permissions": "-",
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
		"attribution_evidence_permissions": "-",
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
		"attribution_evidence_permissions": "-",
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

SYSTEM_MANAGER_CAPABILITIES = frozenset(
	{
		"system.configure",
		"roles.manage",
		"system.recover",
		"student.policy.manage",
		"conversion.execute",
		"student.routing.read",
		"student.sla.read",
	}
)
LEGACY_OVERLAY_IDS = frozenset(LEGACY_COMPATIBILITY_OVERLAYS)
LEGACY_OVERLAY_ROLES = frozenset().union(
	*(LEGACY_COMPATIBILITY_OVERLAYS[overlay]["roles"] for overlay in LEGACY_OVERLAY_IDS)
)
CANONICAL_PROFILE_ROLES = frozenset().union(*PROFILE_ROLE_ALIASES.values())
CRM_POLICY_ROLE_NAMES = tuple(
	sorted(CANONICAL_SELECTABLE_ROLES)
)
CRM_BUSINESS_ROLES = CANONICAL_PROFILE_ROLES
CRM_ALLOWED_ROLES = CANONICAL_SELECTABLE_ROLES
FRAMEWORK_ROLE_NAMES = frozenset({"All", "Guest", "Desk User", "Website User"})
_MIGRATION_ROLE_NAMES = frozenset(
	CRM_ALLOWED_ROLES
	| FRAMEWORK_ROLE_NAMES
	| set(DESK_MANAGEMENT_ROLE_NAMES)
	| LEGACY_UNMAPPED_ROLES
	| LEGACY_OVERLAY_ROLES
	| ROLE_BACKFILL_SOURCES
)

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
	return role_names - _MIGRATION_ROLE_NAMES


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
	# System Manager remains the CRM control plane when it also has known Frappe
	# Desk-management roles. Unknown roles still fail closed above.
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
	"""Resolve the sole Student/Contact scope.

	Reads from the DB-backed `CRM Permission Profile` catalog by default.
	Set site_config `crm_permission_profile_use_hardcoded_matrix` truthy to
	force the pre-cutover hardcoded-matrix behavior back on without a code
	deploy -- a same-second rollback path for this phase's cutover.
	"""
	if administrator:
		return "all"
	if _use_hardcoded_permission_matrix():
		return _hardcoded_case_scope_for_roles(roles, doctype)

	role = _profile_role_for_role_set(roles)
	if role is None:
		return "deny"
	profile = _cached_permission_profile(role)
	if profile is None:
		# `role` resolved to a canonical profile or compatibility overlay
		# identity, so a matching seeded record is expected. Its absence is a
		# real data gap (e.g. a role added after Phase 2's seed ran) and must
		# be surfaced, not silently treated as an ordinary deny.
		_warn_missing_permission_profile(role)
		return "deny"
	scope = profile["row_scope"]
	if scope == "campus_assigned_contact" and doctype != "CRM Contact":
		return "deny"
	return scope


def delete_requires_ownership_for_roles(roles, *, administrator=False):
	"""Whether the resolved profile gates delete on owner-or-assigned (PRD P0-3).

	This is genuinely new behavior with no pre-cutover matrix to fall back to,
	so the kill-switch restores the old no-ownership-check delete behavior
	exactly, same as it restores the old row-scope behavior.
	"""
	if administrator:
		return False
	if _use_hardcoded_permission_matrix():
		return False
	role = _profile_role_for_role_set(roles)
	if role is None:
		return False
	profile = _cached_permission_profile(role)
	if profile is None:
		return False
	return profile["delete_requires_ownership"]


def _hardcoded_case_scope_for_roles(roles, doctype):
	"""Pre-cutover implementation, retained only for the kill-switch above."""
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
	"""Translate the managed permission catalog into managed Frappe DocPerm rows.

	Reads from the DB-backed `CRM Permission Profile` catalog by default; see
	`case_scope_for_roles` for the kill-switch. Deliberately excludes
	`legacy_untouched` surfaces -- callers must leave those existing rows
	alone rather than allowing a future fall-through grant to regenerate them.
	This function only touches the database when actually called, never at
	module import time -- callers must not bind its result to a module-level
	constant.
	"""
	if _use_hardcoded_permission_matrix():
		return _hardcoded_managed_docperm_rows()

	rows_by_doctype = {}
	for role in (SYSTEM_MANAGER_ROLE, *PROFILE_LABELS.values()):
		profile = _cached_permission_profile(role)
		if profile is None:
			_warn_missing_permission_profile(role)
			continue
		for doctype, flags in profile["doctypes"].items():
			row = _docperm_row_from_flags(role, flags)
			if row:
				rows_by_doctype.setdefault(doctype, []).append(row)
	for doctype, rows in rows_by_doctype.items():
		rows_by_doctype[doctype] = sorted(rows, key=lambda row: row["role"])
	return rows_by_doctype


def _hardcoded_managed_docperm_rows():
	"""Pre-cutover implementation, retained only for the kill-switch above."""
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
				if doctype in PHASE9_COMMAND_ONLY_DOCTYPES:
					permission_set = "r"
				row = _docperm_row(role, permission_set)
				if row:
					rows.append(row)
			rows_by_doctype[doctype] = sorted(rows, key=lambda row: row["role"])
	return rows_by_doctype


def _overlay_permission_set(surface, template, doctype):
	if surface == "admissions_case":
		permission_set = template["case_permissions"]
		return permission_set.get(doctype, "-") if isinstance(permission_set, dict) else permission_set
	if surface == "decision_action":
		# Legacy roles retain read visibility during the migration, but never gain
		# a raw write path around the Phase 6 command service.
		return "-" if template["row_scope"] == "no_case_scope" else "r"
	key = {
		"reference": "reference_permissions",
		"acquisition": "acquisition_permissions",
		"governed_acquisition": "governed_acquisition_permissions",
		"governed_admissions": "governed_admissions_permissions",
		"attribution_evidence": "attribution_evidence_permissions",
		"control_plane": "control_permissions",
	}[surface]
	return template[key]


def _docperm_row(role, permission_set):
	if permission_set in {"-", "unchanged"}:
		return None
	if permission_set == "same":
		raise ValueError("Canonical aliases must resolve through a canonical profile")
	return {"role": role, **{field: 1 for verb, field in _PERMISSION_FLAGS.items() if verb in permission_set}}


# ---------------------------------------------------------------------------
# Lazy, cached `CRM Permission Profile` reader.
#
# `case_scope_for_roles()` and `managed_docperm_rows()` above call into this
# section by default; the hardcoded matrices earlier in this module are kept
# only as the `crm_permission_profile_use_hardcoded_matrix` kill-switch's
# fallback. Every DB touch is a local `import frappe` inside a function body,
# never at module import time, so importing this module stays pure Python.
# ---------------------------------------------------------------------------

PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY = "crm_permission_profile_use_hardcoded_matrix"

_PERMISSION_PROFILE_CACHE_TTL_SEC = 300


def _use_hardcoded_permission_matrix():
	import frappe

	return bool(frappe.conf.get(PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY))


def _warn_missing_permission_profile(role):
	import frappe

	frappe.log_error(
		title="CRM Permission Profile missing",
		message=(
			f"Role {role!r} resolved to a canonical profile or compatibility overlay "
			"identity via role_policy.classify_role_set, but no matching CRM Permission "
			"Profile record exists. Falling back to deny for this role until a profile "
			"is seeded/created for it."
		),
	)


def _permission_profile_cache_key(role):
	return f"crm_permission_profile::{role}"


def clear_permission_profile_cache(role):
	"""Invalidate one role's cached profile. Called by the doctype's `on_update`.

	`role` is immutable after a profile is created, so a single key is enough.
	"""
	import frappe

	frappe.cache().delete_value(_permission_profile_cache_key(role))


def _load_permission_profile(role):
	import frappe

	name = frappe.db.get_value("CRM Permission Profile", {"role": role}, "name")
	if not name:
		return None
	doc = frappe.get_doc("CRM Permission Profile", name)
	return {
		"row_scope": doc.row_scope,
		"delete_requires_ownership": bool(doc.delete_requires_ownership),
		"doctypes": {
			row.document_type: {
				"read": bool(row.read),
				"write": bool(row.write),
				"create": bool(row.create),
				"delete": bool(row.delete),
				"export": bool(row.export),
			}
			for row in doc.applicable_doctypes
		},
	}


def _cached_permission_profile(role):
	import frappe

	cache_key = _permission_profile_cache_key(role)
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached
	value = _load_permission_profile(role)
	frappe.cache().set_value(cache_key, value, expires_in_sec=_PERMISSION_PROFILE_CACHE_TTL_SEC)
	return value


def _profile_role_for_role_set(roles):
	"""Return the single literal Role name identity resolution would key on.

	Mirrors `classify_role_set`'s own classification so the DB read queries
	the exact seeded record the pure-Python identity resolution points at.
	Returns ``None`` when no profile or overlay applies (administrator is
	handled by callers before this is reached).
	"""
	role_names = frozenset(roles)
	state = classify_role_set(role_names)
	if state == "system_manager":
		return SYSTEM_MANAGER_ROLE
	if state == "canonical_profile":
		profile = resolve_crm_profile(role_names)
		return PROFILE_LABELS.get(profile)
	if state == "compatibility_overlay":
		overlay = resolve_compatibility_overlay(role_names)
		if not overlay:
			return None
		matched = role_names & LEGACY_COMPATIBILITY_OVERLAYS[overlay]["roles"]
		return next(iter(matched), None)
	return None


def _docperm_row_from_flags(role, flags):
	row = {"role": role, **{verb: 1 for verb, present in flags.items() if present}}
	return row if len(row) > 1 else None
