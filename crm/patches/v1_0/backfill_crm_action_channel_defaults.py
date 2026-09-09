"""Backfill CRM Action ``default_channel`` + ``allowed_time_slots`` from the catalog.

``seed_crm_action_type`` only inserts missing rows, so a site that seeded the
action catalog before the channel / time-slot defaults existed keeps every
non-fixed action at ``default_channel = "NONE"`` with no ``allowed_time_slots``.
That leaves the NBA producer unable to emit a real per-action timing domain
(every action looks unconstrained, so WAIT is unreachable) and unable to drop
channel actions when a student's consent is revoked.

Re-derive both fields from ``defaults_for_action`` for every canonical row and
reconcile the definition digest / revision log exactly as
``add_nba_control_plane._backfill_actions`` does when ``default_channel`` moves.
Custom (non-catalog) actions are left untouched -- their channel is operator config.

Idempotent: values come from a pure function; a second run finds nothing to change.
"""

import json

import frappe

from crm.fcrm.action_constraints import defaults_for_action
from crm.fcrm.action_type_catalog import ACTION_TYPE_METADATA
from crm.fcrm.nba_canonical import action_definition_snapshot, canonical_digest
from crm.patches.v1_0.add_nba_control_plane import (
	_ensure_revision_row,
	_revision_digest_conflict,
)

_FIELDS = [
	"name",
	"code",
	"display_name",
	"action_type",
	"purpose",
	"default_channel",
	"allowed_time_slots",
	"allowed_actors",
	"requires_approval",
	"auto_execute",
	"enabled",
	"definition_revision",
	"definition_digest",
	"effective_from",
	"creation",
]


def execute():
	if not frappe.db.table_exists("CRM Action"):
		return

	for row in frappe.get_all("CRM Action", fields=_FIELDS, limit_page_length=0):
		meta = ACTION_TYPE_METADATA.get(row.get("code") or "")
		if not meta:
			continue

		wanted = defaults_for_action(row["code"], meta["category"])
		updates: dict[str, object] = {}
		if row.get("default_channel") != wanted["default_channel"]:
			updates["default_channel"] = wanted["default_channel"]
		if _slots(row.get("allowed_time_slots")) != _slots(wanted["allowed_time_slots"]):
			updates["allowed_time_slots"] = wanted["allowed_time_slots"]
		if not updates:
			continue

		merged = {**row, **updates, "category": meta["category"]}
		snapshot = action_definition_snapshot(merged)
		digest = canonical_digest(snapshot)
		revision = max(int(row.get("definition_revision") or 0), 1)
		if row.get("definition_digest") != digest:
			if _revision_digest_conflict(row["name"], revision, digest):
				revision += 1
			updates["definition_digest"] = digest
			updates["definition_revision"] = revision

		frappe.db.set_value("CRM Action", row["name"], updates, update_modified=False)
		_ensure_revision_row(row["name"], revision, digest, snapshot)

	if not getattr(frappe.flags, "in_test", False):
		frappe.db.commit()


def _slots(value: object) -> list[str]:
	"""Order-independent slot list from a JSON string / list / empty value."""
	if not value:
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value)
		except json.JSONDecodeError:
			return []
	return sorted(value) if isinstance(value, list) else []
