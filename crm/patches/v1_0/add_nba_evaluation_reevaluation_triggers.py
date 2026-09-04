"""Persist the WAIT re-evaluation boundary on ``CRM NBA Evaluation``.

Phase 05 accepted ``revisit_at`` and ``reevaluation_trigger`` on the evaluation
commit but had nowhere to store them, so a WAIT disposition could not be fired
later. This adds the two columns plus ``reevaluation_dispatched_at`` and a
lookup index for the hourly due-revisit reconciler.

The columns are nullable and only written on a completed WAIT commit, so there
is no backfill: historical rows keep a null boundary and are ignored by the
reconciler. Idempotent -- the DocType reload is a no-op on a second run and the
index change is guarded on ``information_schema``.

Rollback:
  ``ALTER TABLE `tabCRM NBA Evaluation`
     DROP COLUMN revisit_at, DROP COLUMN reevaluation_trigger,
     DROP COLUMN reevaluation_dispatched_at;``
"""

import frappe

_TABLE = "tabCRM NBA Evaluation"
_REVISIT_INDEX = "crm_nba_evaluation_revisit_idx"


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_nba_evaluation")
	if not frappe.db.table_exists("CRM NBA Evaluation"):
		return

	if not _index_exists(_REVISIT_INDEX):
		frappe.db.sql_ddl(
			f"ALTER TABLE `{_TABLE}` ADD INDEX `{_REVISIT_INDEX}` (`status`, `disposition`, `revisit_at`)"
		)

	if not frappe.flags.in_test:
		frappe.db.commit()


def _index_exists(index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
			"AND table_name = %s AND index_name = %s LIMIT 1",
			(_TABLE, index_name),
		)
	)
