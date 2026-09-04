"""Introduce the additive NBA control-plane columns and their revision log.

Adds ``definition_revision`` / ``definition_digest`` / ``effective_from`` /
``effective_to`` to ``tabCRM Action`` and ``policy_revision`` / ``policy_digest``
/ ``effective_from`` / ``effective_to`` to ``tabCRM Timing Policy``, then
backfills a deterministic snapshot digest for every row and records one
immutable ``CRM Action Definition Revision`` per Action revision. Seeds a single
conservative active ``default`` NBA Decision Policy when none exists.

Idempotent: every column add is guarded on ``information_schema`` and every
value is re-derived from a pure snapshot, so a second run is a no-op.

Rollback:
  ``ALTER TABLE `tabCRM Action` DROP COLUMN `definition_revision`,
    DROP COLUMN `definition_digest`, DROP COLUMN `effective_from`,
    DROP COLUMN `effective_to`;``
  ``ALTER TABLE `tabCRM Timing Policy` DROP COLUMN `policy_revision`,
    DROP COLUMN `policy_digest`, DROP COLUMN `effective_from`,
    DROP COLUMN `effective_to`;``
  ``DROP TABLE `tabCRM Action Definition Revision`;``
  ``DROP TABLE `tabCRM NBA Decision Policy`;``
"""

import json

import frappe

from crm.fcrm.nba_canonical import (
	action_definition_snapshot,
	canonical_digest,
	timing_policy_snapshot,
)

_ACTION_COLUMNS = {
	"definition_revision": "int(11) NOT NULL DEFAULT 1",
	"definition_digest": "varchar(140) NULL",
	"effective_from": "datetime(6) NULL",
	"effective_to": "datetime(6) NULL",
}
_TIMING_COLUMNS = {
	"policy_revision": "int(11) NOT NULL DEFAULT 1",
	"policy_digest": "varchar(140) NULL",
	"effective_from": "datetime(6) NULL",
	"effective_to": "datetime(6) NULL",
}
_REVISION_INDEX = "crm_action_definition_revision_action_revision_uniq"


def execute():
	if not frappe.db.table_exists("CRM Action"):
		return

	for doctype in (
		"crm_action",
		"crm_timing_policy",
		"crm_action_definition_revision",
		"crm_nba_decision_policy",
	):
		frappe.reload_doc("fcrm", "doctype", doctype)

	_add_columns("tabCRM Action", _ACTION_COLUMNS)
	if frappe.db.table_exists("CRM Timing Policy"):
		_add_columns("tabCRM Timing Policy", _TIMING_COLUMNS)

	_backfill_actions()
	if frappe.db.table_exists("CRM Timing Policy"):
		_backfill_timing_policies()

	_add_revision_unique_index()
	_seed_default_decision_policy()

	if not frappe.flags.in_test:
		frappe.db.commit()


def _add_columns(table: str, columns: dict[str, str]) -> None:
	for name, ddl in columns.items():
		if not _column_exists(table, name):
			frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD COLUMN `{name}` {ddl}")


def _column_exists(table: str, column: str) -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() "
			"AND table_name = %s AND column_name = %s LIMIT 1",
			(table, column),
		)
	)


def _backfill_actions() -> None:
	from crm.fcrm.action_type_catalog import ACTION_TYPE_METADATA

	rows = frappe.get_all(
		"CRM Action",
		fields=[
			"name",
			"code",
			"display_name",
			"action_type",
			"purpose",
			"default_channel",
			"allowed_actors",
			"requires_approval",
			"auto_execute",
			"enabled",
			"definition_revision",
			"definition_digest",
			"effective_from",
			"creation",
		],
		limit_page_length=0,
	)
	for row in rows:
		row["category"] = ACTION_TYPE_METADATA.get(row.get("code") or "", {}).get("category")
		snapshot = action_definition_snapshot(row)
		digest = canonical_digest(snapshot)
		revision = max(int(row.get("definition_revision") or 0), 1)
		updates: dict[str, object] = {}
		if not row.get("effective_from"):
			updates["effective_from"] = row.get("creation")
		if row.get("definition_digest") != digest:
			# A revision row is immutable. If one already exists for this revision
			# with a different digest, the snapshot genuinely changed since it was
			# recorded, so advance to a new revision rather than leaving the log
			# out of sync with the column.
			if _revision_digest_conflict(row["name"], revision, digest):
				revision += 1
			updates["definition_digest"] = digest
			updates["definition_revision"] = revision
		if updates:
			frappe.db.set_value("CRM Action", row["name"], updates, update_modified=False)
		_ensure_revision_row(row["name"], revision, digest, snapshot)


def _revision_digest_conflict(action: str, revision: int, digest: str) -> bool:
	existing = frappe.db.get_value(
		"CRM Action Definition Revision", {"action": action, "revision": revision}, "digest"
	)
	return existing is not None and existing != digest


def _ensure_revision_row(action: str, revision: int, digest: str, snapshot: dict) -> None:
	if frappe.db.exists("CRM Action Definition Revision", {"action": action, "revision": revision}):
		return
	frappe.get_doc(
		{
			"doctype": "CRM Action Definition Revision",
			"action": action,
			"revision": revision,
			"digest": digest,
			"snapshot": snapshot,
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)


def _backfill_timing_policies() -> None:
	rows = frappe.get_all(
		"CRM Timing Policy",
		fields=[
			"name",
			"trigger_type",
			"delay_value",
			"delay_unit",
			"allowed_start_time",
			"allowed_end_time",
			"deadline_type",
			"deadline_offset",
			"recurrence_type",
			"recurrence_interval",
			"policy_revision",
			"policy_digest",
			"effective_from",
			"creation",
		],
		limit_page_length=0,
	)
	for row in rows:
		digest = canonical_digest(timing_policy_snapshot(row))
		revision = max(int(row.get("policy_revision") or 0), 1)
		updates: dict[str, object] = {}
		if not row.get("effective_from"):
			updates["effective_from"] = row.get("creation")
		if row.get("policy_digest") != digest:
			updates["policy_digest"] = digest
			updates["policy_revision"] = revision
		if updates:
			frappe.db.set_value("CRM Timing Policy", row["name"], updates, update_modified=False)


def _add_revision_unique_index() -> None:
	table = "tabCRM Action Definition Revision"
	if not frappe.db.table_exists("CRM Action Definition Revision"):
		return
	existing = frappe.db.sql(
		"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
		"AND table_name = %s AND index_name = %s LIMIT 1",
		(table, _REVISION_INDEX),
	)
	if not existing:
		frappe.db.sql_ddl(
			f"ALTER TABLE `{table}` ADD UNIQUE INDEX `{_REVISION_INDEX}` (`action`, `revision`)"
		)


def _seed_default_decision_policy() -> None:
	if not frappe.db.table_exists("CRM NBA Decision Policy"):
		return
	if frappe.db.exists("CRM NBA Decision Policy", {"policy_key": "default"}):
		return
	frappe.get_doc(
		{
			"doctype": "CRM NBA Decision Policy",
			"policy_key": "default",
			"is_active": 1,
			"top_n": 3,
			"max_recommendations": 10,
			"min_score_threshold": 0.0,
			"diversity_rule": "unique_action_type",
			"conflict_key_fields": json.dumps(["conflict_key"]),
		}
	).insert(ignore_permissions=True)
