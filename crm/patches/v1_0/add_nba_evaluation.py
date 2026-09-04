"""Additive schema for the durable, feature-gated NBA Evaluation runtime.

Reloads the standalone ``CRM NBA Evaluation`` aggregate and ensures its lookup
indexes -- a composite ``(student, status)`` for the reconciler and a plain
``(evaluation_key)`` index for identity lookups. ``evaluation_key`` is a dedup
token, not a uniqueness guarantee: a privileged force-rerun deliberately creates
a second run over an unchanged governed identity, so any stale UNIQUE index on
that column left by an earlier schema is dropped here. Idempotency is enforced
by the unique ``request_idempotency_key`` column instead.

The table is introduced empty (the runtime is disabled by default), so there is
no backfill. Idempotent: the DocType reload is a no-op on a second run and every
index change is guarded on ``information_schema``.

Rollback:
  ``DROP TABLE `tabCRM NBA Evaluation`;``
"""

import frappe

_TABLE = "tabCRM NBA Evaluation"
_STUDENT_STATUS_INDEX = "crm_nba_evaluation_student_status_idx"
_EVALUATION_KEY_INDEX = "crm_nba_evaluation_evaluation_key_idx"


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_nba_evaluation")
	if not frappe.db.table_exists("CRM NBA Evaluation"):
		return

	for index_name in _unique_indexes_on("evaluation_key"):
		frappe.db.sql_ddl(f"ALTER TABLE `{_TABLE}` DROP INDEX `{index_name}`")

	if not _index_exists(_STUDENT_STATUS_INDEX):
		frappe.db.sql_ddl(f"ALTER TABLE `{_TABLE}` ADD INDEX `{_STUDENT_STATUS_INDEX}` (`student`, `status`)")

	if not _column_has_index("evaluation_key"):
		frappe.db.sql_ddl(f"ALTER TABLE `{_TABLE}` ADD INDEX `{_EVALUATION_KEY_INDEX}` (`evaluation_key`)")

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


def _column_has_index(column: str) -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
			"AND table_name = %s AND column_name = %s AND seq_in_index = 1 LIMIT 1",
			(_TABLE, column),
		)
	)


def _unique_indexes_on(column: str) -> list[str]:
	rows = frappe.db.sql(
		"SELECT DISTINCT index_name FROM information_schema.statistics WHERE table_schema = DATABASE() "
		"AND table_name = %s AND column_name = %s AND seq_in_index = 1 AND non_unique = 0 AND index_name <> 'PRIMARY'",
		(_TABLE, column),
	)
	return [row[0] for row in rows]
