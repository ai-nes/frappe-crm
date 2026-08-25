"""Migrate the duplicate ``Sales`` role to canonical ``Sale`` safely.

The original Phase 2 migration may already have run on a site, so changing
source fixtures alone would leave existing users, DocPerm rows, and AI grants
behind. This forward patch cleans those database records while leaving mixed
accounts for explicit review.
"""

import frappe

from crm.api.user import set_canonical_crm_profile
from crm.fcrm.role_policy import (
	CANONICAL_PROFILE_ROLES,
	CRM_ALLOWED_ROLES,
	FRAMEWORK_ROLE_NAMES,
	LEGACY_UNMAPPED_ROLES,
	ROLE_BACKFILL_SOURCES,
	ROLE_BACKFILL_TARGETS,
)
from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms

RETIRED_ROLE = "Sales"
CANONICAL_ROLE = "Sale"
_BLOCKING_ROLES = {"Administrator", "System Manager"} | (
	LEGACY_UNMAPPED_ROLES - {RETIRED_ROLE}
)


def _target_for_roles(roles):
	"""Return ``Sale`` only when the retired role has no conflicting profile."""
	role_names = set(roles)
	if RETIRED_ROLE not in role_names or role_names & _BLOCKING_ROLES:
		return None
	unknown_roles = role_names - CRM_ALLOWED_ROLES - FRAMEWORK_ROLE_NAMES - LEGACY_UNMAPPED_ROLES
	if unknown_roles:
		return None

	targets = {CANONICAL_ROLE}
	for role in role_names & CANONICAL_PROFILE_ROLES:
		targets.add(role)
	for role in role_names & ROLE_BACKFILL_SOURCES:
		targets.add(ROLE_BACKFILL_TARGETS[role])

	return CANONICAL_ROLE if targets == {CANONICAL_ROLE} else None


def _migrate_user(user):
	user_doc = frappe.get_doc("User", user)
	user_doc.set("roles", [row for row in user_doc.roles if row.role != RETIRED_ROLE])
	set_canonical_crm_profile(user_doc, CANONICAL_ROLE)
	user_doc.save(ignore_permissions=True)


def execute():
	"""Migrate unambiguous accounts and remove stale runtime grants."""
	frappe.db.savepoint("retire_duplicate_sales_role")
	result = {"migrated": [], "conflicts": []}
	try:
		for user in frappe.get_all("User", pluck="name"):
			if user in {"Administrator", "Guest"}:
				continue
			roles = set(frappe.get_roles(user))
			if RETIRED_ROLE not in roles:
				continue
			if _target_for_roles(roles) != CANONICAL_ROLE:
				result["conflicts"].append(user)
				continue
			_migrate_user(user)
			result["migrated"].append(user)

		# Rebuild managed DocPerms so deployed sites lose the retired role rows,
		# while legacy-untouched DocTypes remain outside the adapter.
		apply_managed_docperms()
		frappe.db.delete(
			"CRM AI Capability Grant",
			{
				"parent": RETIRED_ROLE,
				"parenttype": "Role",
				"parentfield": "custom_ai_capability_grants",
			},
		)
		if result["conflicts"]:
			frappe.logger("crm").warning(
				"retire_duplicate_sales_role conflicts=%s",
				",".join(sorted(result["conflicts"])),
			)
	except Exception:
		frappe.db.rollback(save_point="retire_duplicate_sales_role")
		raise

	frappe.clear_cache()
	return result
