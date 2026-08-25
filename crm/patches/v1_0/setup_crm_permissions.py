"""Database adapter for the versioned Phase 2 DocPerm policy.

The policy catalog in :mod:`crm.fcrm.role_policy` is the only source of CRM
role grants. This module translates that catalog into live DocPerm rows; it
never writes generated permission JSON into the deployed source tree.
"""

import frappe

from crm.fcrm.role_policy import (
	CRM_POLICY_ROLE_NAMES,
	LEGACY_OVERLAY_ROLES,
	LEGACY_UNMAPPED_ROLES,
	ROLE_BACKFILL_SOURCES,
	managed_docperm_rows,
)

DOCTYPE_PERMS = managed_docperm_rows()
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

# Historical patches import these names. They remain policy-derived aliases so
# rerunning an old patch cannot bring back a second permission catalog.
EDUCATION_PROGRAM_PERMS = DOCTYPE_PERMS["CRM Education Program"]
MARKETING_LOOKUP_PERMS = DOCTYPE_PERMS["CRM Lead Source"]
LOST_REASON_PERMS = DOCTYPE_PERMS["CRM Lost Reason"]
CAMPUS_PERMS = DOCTYPE_PERMS["CRM Campus"]


def apply_managed_docperms():
	"""Replace DocPerm rows only for surfaces owned by the Phase 2 matrix.

	`legacy_untouched` doctypes never appear in ``DOCTYPE_PERMS`` and are
	therefore intentionally left byte-for-byte outside this adapter.
	"""
	for doctype, permissions in DOCTYPE_PERMS.items():
		# Custom and integration roles may have their own DocPerm rows. Replace
		# only the rows this policy owns; never erase site-specific grants.
		frappe.db.delete("DocPerm", {"parent": doctype, "role": ["in", MANAGED_DOCPERM_ROLE_NAMES]})
		for permission in permissions:
			frappe.get_doc(
				{
					"doctype": "DocPerm",
					"parent": doctype,
					"parenttype": "DocType",
					"parentfield": "permissions",
					"permlevel": 0,
					**permission,
				}
			).insert(ignore_permissions=True)


def execute():
	"""Compatibility entry point for historical setup patches."""
	apply_managed_docperms()
	frappe.clear_cache()
