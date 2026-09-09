"""Introduce the additive NBA control-plane columns.

Adds ``definition_revision`` / ``definition_digest`` / ``effective_from`` /
``effective_to`` to ``tabCRM Action`` and ``policy_revision`` / ``policy_digest``
/ ``effective_from`` / ``effective_to`` to ``tabCRM Timing Policy``, then
backfills a deterministic snapshot digest for every row. Seeds a single
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


def execute():
	if not frappe.db.table_exists("CRM Action"):
		return

	for doctype in ("crm_action", "crm_timing_policy", "crm_nba_decision_policy"):
		frappe.reload_doc("fcrm", "doctype", doctype)

	_add_columns("tabCRM Action", _ACTION_COLUMNS)
	if frappe.db.table_exists("CRM Timing Policy"):
		_add_columns("tabCRM Timing Policy", _TIMING_COLUMNS)

	_backfill_actions()
	if frappe.db.table_exists("CRM Timing Policy"):
		_backfill_timing_policies()

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
			updates["definition_digest"] = digest
			updates["definition_revision"] = revision
		if updates:
			frappe.db.set_value("CRM Action", row["name"], updates, update_modified=False)


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
			"kernel_policy": json.dumps({
				"revision": "nba-decision-policy-r1",
				"score_threshold": 0.35,
				"confidence_floor": 0.45,
				"top_n_cap": 3,
				"recommendation_ttl_seconds": 604800,
				"component_weights": {"opportunity_fit": 0.45, "urgency": 0.25, "effectiveness_index": 0.30},
				"recent_contact_days": 2,
				"cooling_contact_days": 5,
				"contact_pressure_penalty": 0.15,
				"redundancy_penalty": 0.10,
				"diversity_group_penalty": 0.05,
				"deadline_horizon_days": 30,
			}, sort_keys=True),
		}
	).insert(ignore_permissions=True)
