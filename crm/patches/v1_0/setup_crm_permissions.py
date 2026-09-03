"""Database adapter for the versioned Phase 2 DocPerm policy.

The policy catalog in :mod:`crm.fcrm.role_policy` is the only source of CRM
role grants. This module translates that catalog into live DocPerm rows; it
never writes generated permission JSON into the deployed source tree.
"""

import json

import frappe

from crm.fcrm.role_policy import (
	CRM_POLICY_ROLE_NAMES,
	LEGACY_OVERLAY_ROLES,
	LEGACY_UNMAPPED_ROLES,
	ROLE_BACKFILL_SOURCES,
	managed_docperm_rows,
)

# Frappe's username ``Administrator`` is the sole platform-superuser exception.
# A regular account merely assigned the raw Administrator role remains unmapped,
# so its historic DocPerm rows must be removed from policy-managed surfaces.
MANAGED_DOCPERM_ROLE_NAMES = tuple(
	sorted(
		set(CRM_POLICY_ROLE_NAMES)
		| LEGACY_OVERLAY_ROLES
		| ROLE_BACKFILL_SOURCES
		| LEGACY_UNMAPPED_ROLES
		| {"Administrator"}
	)
)


def get_doctype_perms():
	"""Lazy accessor for the managed DocPerm rows, keyed by doctype.

	Deliberately a function, not a module-level constant: `managed_docperm_rows()`
	now reads from the `CRM Permission Profile` table, so binding its result at
	import time would touch the database just from importing this module.
	"""
	return managed_docperm_rows()


# Historical patches import these names. They remain policy-derived aliases so
# rerunning an old patch cannot bring back a second permission catalog. Each is
# a lazy accessor for the same reason as `get_doctype_perms` above.
def get_education_program_perms():
	return get_doctype_perms()["CRM Education Program"]


def get_marketing_lookup_perms():
	return get_doctype_perms()["CRM Lead Source"]


def get_lost_reason_perms():
	return get_doctype_perms()["CRM Term"]


def get_campus_perms():
	return get_doctype_perms()["CRM Campus"]


_SYNC_STATE_DOCTYPE = "FCRM Settings"
_SYNC_STATE_FIELD = "managed_docperm_sync_state"
_DOCPERM_FLAG_FIELDS = ("read", "write", "create", "delete", "export")


def _load_previously_synced_pairs():
	raw = frappe.db.get_single_value(_SYNC_STATE_DOCTYPE, _SYNC_STATE_FIELD)
	if not raw:
		return set()
	return {tuple(pair) for pair in json.loads(raw)}


def _save_synced_pairs(pairs):
	frappe.db.set_single_value(_SYNC_STATE_DOCTYPE, _SYNC_STATE_FIELD, json.dumps(sorted(pairs)))


def _existing_docperm_flags(doctype, role):
	name = frappe.db.get_value(
		"DocPerm", {"parent": doctype, "parenttype": "DocType", "role": role, "permlevel": 0}, "name"
	)
	if not name:
		return None
	doc = frappe.get_doc("DocPerm", name)
	return {field: bool(doc.get(field)) for field in _DOCPERM_FLAG_FIELDS}


def _permission_matches(existing, desired):
	if existing is None:
		return False
	return existing == {field: bool(desired.get(field)) for field in _DOCPERM_FLAG_FIELDS}


def _replace_docperm_row(doctype, role, permission):
	# `DocPerm` field defaults set `create`/`delete`/`export` to 1, so any flag
	# missing from `permission` must be forced to 0 explicitly here -- leaving
	# it unset would silently grant it, which is both an over-grant and the
	# reason an unset flag could never round-trip through `_permission_matches`.
	flags = {field: 1 if permission.get(field) else 0 for field in _DOCPERM_FLAG_FIELDS}
	frappe.db.delete("DocPerm", {"parent": doctype, "parenttype": "DocType", "role": role, "permlevel": 0})
	frappe.get_doc(
		{
			"doctype": "DocPerm",
			"parent": doctype,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"permlevel": 0,
			"role": role,
			**flags,
		}
	).insert(ignore_permissions=True)


def apply_managed_docperms():
	"""Idempotently sync only the doctype/role pairs currently managed.

	Only writes a DocPerm row when its CRUD flags actually differ from what
	the current policy declares, and only removes a row that this patch
	itself synced on a previous run but no longer appears in the current
	managed set (e.g. a doctype dropped from a `CRM Permission Profile`).
	Rows this patch never created -- unmanaged roles, `legacy_untouched`
	doctypes (which never appear in `get_doctype_perms()`), or hand-added
	grants outside the managed set -- are never read, written, or deleted.
	"""
	desired = get_doctype_perms()
	current_pairs = set()

	for doctype, permissions in desired.items():
		for permission in permissions:
			role = permission["role"]
			current_pairs.add((doctype, role))
			if not _permission_matches(_existing_docperm_flags(doctype, role), permission):
				_replace_docperm_row(doctype, role, permission)

	previously_synced = _load_previously_synced_pairs()
	for doctype, role in previously_synced - current_pairs:
		frappe.db.delete("DocPerm", {"parent": doctype, "parenttype": "DocType", "role": role, "permlevel": 0})

	_save_synced_pairs(current_pairs)


def execute():
	"""Compatibility entry point for historical setup patches."""
	apply_managed_docperms()
	frappe.clear_cache()
