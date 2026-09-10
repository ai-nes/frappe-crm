"""Repair legacy role references left by pre-cutover installs.

The main migration is one-shot in Frappe.  This follow-up patch is intentionally
small and migration-only: it does not expose aliases to request-time auth, but
it cleans persisted child rows (including non-User Has Role parents) on sites
that had already recorded the original cutover as complete.
"""

import frappe

from crm.patches.v1_0.migrate_to_canonical_crm_roles import (
	_assert_no_legacy_references,
	_delete_legacy_roles,
	_require_maintenance_window,
	_replace_role_references,
	_write_snapshot_once,
)


def execute():
	_require_maintenance_window()
	_write_snapshot_once(capture_mode="pre_cutover_repair")
	try:
		_replace_role_references()
		_delete_legacy_roles()
		_assert_no_legacy_references()
		frappe.db.commit()
		frappe.clear_cache()
	except Exception:
		frappe.db.rollback()
		raise
