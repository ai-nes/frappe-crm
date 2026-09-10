"""Additive evaluation-epoch schema on CRM Recommendation and CRM NBA Evaluation.

Adds an optional ``evaluation`` link plus the immutable kernel payload
(``ai_payload``), its per-recommendation key (``recommendation_key``) and
``rank`` to ``tabCRM Recommendation``, and an ``evaluation_trace`` column to
``tabCRM NBA Evaluation``. A composite ``UNIQUE (evaluation, recommendation_key)``
index stops one evaluation holding two rows for the same kernel key; legacy rows
keep a NULL ``evaluation`` and MariaDB treats NULL tuples as distinct, so they
are unaffected.

The columns are introduced empty -- legacy recommendations leave every new
column blank and keep their existing autoname and lifecycle projection -- so
there is no backfill. Idempotent: every column and index change is guarded on
``information_schema``.

Rollback:
  ``ALTER TABLE `tabCRM Recommendation` DROP INDEX `crm_recommendation_evaluation_key_uniq`,
    DROP COLUMN `evaluation`, DROP COLUMN `ai_payload`,
    DROP COLUMN `recommendation_key`, DROP COLUMN `rank`;``
  ``ALTER TABLE `tabCRM NBA Evaluation` DROP COLUMN `evaluation_trace`;``
"""

import frappe

_RECOMMENDATION_TABLE = "tabCRM Recommendation"
_EVALUATION_TABLE = "tabCRM NBA Evaluation"
_UNIQUE_INDEX = "crm_recommendation_evaluation_key_uniq"

_RECOMMENDATION_COLUMNS = {
	"evaluation": "varchar(140) NULL",
	"ai_payload": "longtext NULL",
	"recommendation_key": "varchar(140) NULL",
	"rank": "int(11) NOT NULL DEFAULT 0",
}
_EVALUATION_COLUMNS = {
	"evaluation_trace": "longtext NULL",
}


def execute():
	if not frappe.db.table_exists("CRM Recommendation"):
		return

	frappe.reload_doc("fcrm", "doctype", "crm_recommendation")
	if frappe.db.table_exists("CRM NBA Evaluation"):
		frappe.reload_doc("fcrm", "doctype", "crm_nba_evaluation")

	_add_columns(_RECOMMENDATION_TABLE, _RECOMMENDATION_COLUMNS)
	if frappe.db.table_exists("CRM NBA Evaluation"):
		_add_columns(_EVALUATION_TABLE, _EVALUATION_COLUMNS)

	_add_unique_index()

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


def _add_unique_index() -> None:
	if _column_exists(_RECOMMENDATION_TABLE, "evaluation") and not _index_exists(_UNIQUE_INDEX):
		frappe.db.sql_ddl(
			f"ALTER TABLE `{_RECOMMENDATION_TABLE}` ADD UNIQUE INDEX `{_UNIQUE_INDEX}` "
			"(`evaluation`, `recommendation_key`)"
		)


def _index_exists(index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
			"AND table_name = %s AND index_name = %s LIMIT 1",
			(_RECOMMENDATION_TABLE, index_name),
		)
	)
