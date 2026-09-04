"""Additive narration columns on ``CRM Recommendation``.

Adds ``rationale_vi`` (the best-effort model narration of a committed
recommendation) and ``rationale_source`` (where it came from, for
observability). Both are nullable and introduced empty -- narration is a
post-commit, best-effort pass, so there is no backfill. Write-once semantics
for ``rationale_vi`` are enforced in the doctype controller and by the fenced
``set_recommendation_rationale`` command, not at the schema level. Idempotent:
every column change is guarded on ``information_schema``.

Rollback:
  ``ALTER TABLE `tabCRM Recommendation`
     DROP COLUMN rationale_vi, DROP COLUMN rationale_source;``
"""

import frappe

_TABLE = "tabCRM Recommendation"
_COLUMNS = {
	"rationale_vi": "longtext NULL",
	"rationale_source": "varchar(140) NULL",
}


def execute():
	if not frappe.db.table_exists("CRM Recommendation"):
		return

	frappe.reload_doc("fcrm", "doctype", "crm_recommendation")
	_add_columns(_TABLE, _COLUMNS)

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
