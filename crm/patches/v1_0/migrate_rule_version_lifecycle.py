"""Migrate the retired ``superseded`` rule snapshot state to ``archived``.

The rule registry contract is now ``draft -> testing -> active -> archived``.
Existing immutable snapshots keep their historical superseded timestamps and
are copied to the explicit archive fields introduced with the new DocType
schema.  The patch is idempotent and runs after model sync.
"""

import frappe


def execute():
	if not frappe.db.table_exists("CRM Rule Version"):
		return

	frappe.db.sql(
		"""
		UPDATE `tabCRM Rule Version`
		SET status = 'archived',
			archived_at = COALESCE(archived_at, superseded_at, NOW()),
			archived_by = COALESCE(archived_by, superseded_by)
		WHERE status = 'superseded'
		"""
	)
	if frappe.db.table_exists("CRM Rule"):
		frappe.db.sql(
			"UPDATE `tabCRM Rule` SET status = 'archived' WHERE status = 'superseded'"
		)

	if not frappe.flags.in_test:
		frappe.db.commit()
