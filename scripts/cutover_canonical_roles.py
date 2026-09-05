"""Direct, idempotent CRM role cutover.

This is intentionally a manually invoked operational command, not a Frappe
migration patch. It changes only role/permission metadata and user role
assignments; business CRM rows are not deleted.
"""

from __future__ import annotations

import frappe

from crm.fcrm.role_policy import CANONICAL_SELECTABLE_ROLES, SYSTEM_MANAGER_ROLE
from crm.patches.v1_0.seed_crm_permission_profiles import execute as seed_profiles
from crm.patches.v1_0.seed_new_lead_role_profiles import execute as seed_lead_profiles
from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms
from crm.patches.v1_0.setup_crm_roles import create_roles


CANONICAL_ROLES = frozenset(
	{
		"CTV Sale",
		"Sale",
		"Lead Sale",
		"Promoter",
		"Lead Promoter",
		"Marketing",
		"Lead Marketing",
		"Admissions Director",
		"Administrator",
	}
)
PLATFORM_ROLES = frozenset({"All", "Guest", "Desk User", "Website User", SYSTEM_MANAGER_ROLE})
LEGACY_ROLE_MAP = {
	"Sales Manager": "Lead Sale",
	"CTV Sale": "CTV Sale",
	"Promoter": "Promoter",
	"Lead Marketing": "Lead Marketing",
	"Marketing": "Marketing",
	"Admissions Director": "Admissions Director",
	"Giám đốc Tuyển sinh": "Admissions Director",
	"Sale": "Sale",
	"CEO": "Administrator",
}


def _role_rows():
	return frappe.get_all("Role", fields=["name"], limit_page_length=0)


def _ensure_user_role(user: str, role: str):
	if not frappe.db.exists("Has Role", {"parent": user, "parenttype": "User", "role": role}):
		frappe.get_doc(
			{
				"doctype": "Has Role",
				"parent": user,
				"parenttype": "User",
				"parentfield": "roles",
				"role": role,
			}
		).insert(ignore_permissions=True)


def _replace_user_roles():
	changed = []
	for row in frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": ["in", list(LEGACY_ROLE_MAP)]},
		fields=["name", "parent", "role"],
		limit_page_length=0,
	):
		target = LEGACY_ROLE_MAP[row.role]
		_ensure_user_role(row.parent, target)
		frappe.db.delete("Has Role", {"name": row.name})
		changed.append({"user": row.parent, "from": row.role, "to": target})

	# Existing system operators get the new visible control role. Keep the
	# Frappe System Manager primitive during the transition for recovery.
	for row in frappe.get_all(
		"Has Role",
		filters={"parenttype": "User", "role": SYSTEM_MANAGER_ROLE},
		fields=["parent"],
		limit_page_length=0,
	):
		if row.parent != "Administrator":
			_ensure_user_role(row.parent, "Administrator")
	return changed


def _delete_role_references(role: str):
	for doctype, field in (
		("Has Role", "role"),
		("DocPerm", "role"),
		("Custom DocPerm", "role"),
		("CRM AI Capability Grant", "parent"),
		("Invitation", "role"),
		("User Permission", "applicable_for"),
	):
		if frappe.db.table_exists(doctype) and frappe.db.has_column(doctype, field):
			frappe.db.delete(doctype, {field: role})


def _remove_noncanonical_roles():
	removed = []
	keep = CANONICAL_ROLES | PLATFORM_ROLES
	for row in _role_rows():
		role = row.name
		if role in keep:
			continue
		_delete_role_references(role)
		if frappe.db.exists("CRM Permission Profile", {"role": role}):
			for profile in frappe.get_all("CRM Permission Profile", filters={"role": role}, pluck="name"):
				frappe.delete_doc("CRM Permission Profile", profile, ignore_permissions=True, force=True)
		if frappe.db.exists("Role", role):
			frappe.delete_doc("Role", role, ignore_permissions=True, force=True)
		removed.append(role)
	return removed


def _reset_permission_profiles():
	for profile in frappe.get_all("CRM Permission Profile", fields=["name", "role"], limit_page_length=0):
		if profile.role not in CANONICAL_ROLES:
			frappe.delete_doc("CRM Permission Profile", profile.name, ignore_permissions=True, force=True)
	seed_profiles()
	seed_lead_profiles()
	# System Manager remains a Frappe technical role, but must not remain a
	# visible CRM business permission profile; Administrator is the control role.
	if frappe.db.exists("CRM Permission Profile", SYSTEM_MANAGER_ROLE):
		frappe.delete_doc(
			"CRM Permission Profile", SYSTEM_MANAGER_ROLE, ignore_permissions=True, force=True
		)
	apply_managed_docperms()


def execute():
	"""Apply the canonical catalog and return an auditable change summary."""
	create_roles(sorted(CANONICAL_ROLES))
	role_changes = _replace_user_roles()
	removed_roles = _remove_noncanonical_roles()
	_reset_permission_profiles()
	frappe.db.commit()
	frappe.clear_cache()
	return {
		"canonical_roles": sorted(CANONICAL_ROLES),
		"role_changes": role_changes,
		"removed_roles": removed_roles,
		"permission_profiles": sorted(
			frappe.get_all("CRM Permission Profile", pluck="role", limit_page_length=0)
		),
	}


def verify():
	"""Fail if a non-platform role or profile remains in the live catalog."""
	roles = {row.name for row in _role_rows()}
	unexpected_roles = sorted(roles - CANONICAL_ROLES - PLATFORM_ROLES)
	profiles = set(frappe.get_all("CRM Permission Profile", pluck="role", limit_page_length=0))
	unexpected_profiles = sorted(profiles - CANONICAL_ROLES)
	if unexpected_roles or unexpected_profiles:
		frappe.throw(
			f"Canonical role verification failed: roles={unexpected_roles}, profiles={unexpected_profiles}"
		)
	return {
		"roles": sorted(roles & (CANONICAL_ROLES | PLATFORM_ROLES)),
		"profiles": sorted(profiles),
		"legacy_roles": unexpected_roles,
		"legacy_profiles": unexpected_profiles,
	}
