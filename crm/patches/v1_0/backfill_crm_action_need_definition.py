"""Refresh CRM Action definition digests after adding the Need link."""

import frappe

from crm.fcrm.action_type_catalog import ACTION_TYPE_METADATA
from crm.fcrm.nba_canonical import action_definition_snapshot, canonical_digest
from crm.patches.v1_0.add_nba_control_plane import (
	_ensure_revision_row,
	_revision_digest_conflict,
)


def execute():
	"""Backfill the new snapshot key without changing configured Actions."""
	if not frappe.db.table_exists("CRM Action") or not frappe.db.table_exists(
		"CRM Action Definition Revision"
	):
		return

	rows = frappe.get_all(
		"CRM Action",
		fields=[
			"name",
			"code",
			"display_name",
			"action_type",
			"need",
			"purpose",
			"default_channel",
			"allowed_actors",
			"requires_approval",
			"requires_parent_authority",
			"academic_constraint",
			"auto_execute",
			"enabled",
			"definition_revision",
			"definition_digest",
		],
		limit_page_length=0,
	)
	for row in rows:
		row["category"] = ACTION_TYPE_METADATA.get(row.get("code") or "", {}).get("category") or row.get(
			"action_type"
		)
		snapshot = action_definition_snapshot(row)
		digest = canonical_digest(snapshot)
		revision = max(int(row.get("definition_revision") or 0), 1)
		if row.get("definition_digest") != digest:
			if _revision_digest_conflict(row["name"], revision, digest):
				revision += 1
			frappe.db.set_value(
				"CRM Action",
				row["name"],
				{"definition_digest": digest, "definition_revision": revision},
				update_modified=False,
			)
		_ensure_revision_row(row["name"], revision, digest, snapshot)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
