"""Enforce the five-role CRM catalog after legacy permission regeneration."""

from __future__ import annotations

import frappe

from crm.fcrm.role_policy import CANONICAL_SELECTABLE_ROLES, LEGACY_UNMAPPED_ROLES
from crm.patches.v1_0.migrate_to_canonical_crm_roles import (
	_assert_no_legacy_references,
	_delete_legacy_roles,
	_require_maintenance_window,
	_replace_role_references,
)
from crm.patches.v1_0.setup_crm_permissions import apply_managed_docperms
from crm.patches.v1_0.setup_crm_roles import create_roles


UNMAPPED_REFERENCE_SPECS = (
	("Has Role", "role"),
	("DocPerm", "role"),
	("Custom DocPerm", "role"),
	("CRM AI Capability Grant", "parent"),
	("Invitation", "role"),
)


def _assert_unmapped_roles_are_unreferenced() -> None:
	for role in sorted(LEGACY_UNMAPPED_ROLES):
		for doctype, field in UNMAPPED_REFERENCE_SPECS:
			if frappe.db.table_exists(doctype) and frappe.db.has_column(doctype, field):
				if frappe.db.exists(doctype, {field: role}):
					raise frappe.ValidationError(
						f"Cannot remove unmapped legacy role {role!r}; reference remains in {doctype}"
					)


def _delete_unmapped_roles() -> None:
	for role in sorted(LEGACY_UNMAPPED_ROLES):
		if frappe.db.exists("Role", role):
			frappe.delete_doc("Role", role, ignore_permissions=True, force=True)


def execute():
	"""Keep live CRM roles canonical while retaining migration-only mappings."""
	_require_maintenance_window()
	try:
		create_roles(sorted(CANONICAL_SELECTABLE_ROLES))
		_replace_role_references()
		_assert_unmapped_roles_are_unreferenced()
		_delete_legacy_roles()
		_delete_unmapped_roles()
		apply_managed_docperms()
		_assert_no_legacy_references()
		frappe.db.commit()
		frappe.clear_cache()
	except Exception:
		frappe.db.rollback()
		raise
