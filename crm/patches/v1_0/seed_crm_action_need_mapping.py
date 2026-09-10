"""Assign the canonical detailed CRM Need to each catalog CRM Action."""

import frappe

from crm.fcrm.action_need import ACTION_NEED_CODE_BY_ACTION
from crm.fcrm.action_type_catalog import ACTION_TYPE_METADATA
from crm.fcrm.nba_canonical import action_definition_snapshot, canonical_digest
from crm.patches.v1_0.add_nba_control_plane import (
	_ensure_revision_row,
	_revision_digest_conflict,
)


def execute():
	"""Backfill the 79 canonical Action-to-Need assignments idempotently."""
	if not frappe.db.table_exists("CRM Action") or not frappe.db.table_exists("CRM Need"):
		return

	has_revisions = frappe.db.table_exists("CRM Action Definition Revision")
	rows = frappe.get_all(
		"CRM Action",
		fields=[
			"name",
			"code",
			"need",
			"display_name",
			"action_type",
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
		if row.get("code") not in ACTION_NEED_CODE_BY_ACTION:
			continue
		need_code = ACTION_NEED_CODE_BY_ACTION[row["code"]]
		need_name = None
		if need_code:
			need_name = frappe.db.get_value("CRM Need", {"code": need_code}, "name")
			if not need_name:
				frappe.throw(f"CRM Need {need_code} is required by Action {row['code']}.")

		updates = {}
		if row.get("need") != need_name:
			updates["need"] = need_name
		row["need"] = need_name
		if has_revisions:
			row["category"] = ACTION_TYPE_METADATA.get(row.get("code") or "", {}).get("category") or row.get(
				"action_type"
			)
			snapshot = action_definition_snapshot(row)
			digest = canonical_digest(snapshot)
			revision = max(int(row.get("definition_revision") or 0), 1)
			if row.get("definition_digest") != digest:
				if _revision_digest_conflict(row["name"], revision, digest):
					revision += 1
				updates.update({"definition_digest": digest, "definition_revision": revision})
			_ensure_revision_row(row["name"], revision, digest, snapshot)
		if updates:
			frappe.db.set_value("CRM Action", row["name"], updates, update_modified=False)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()
