"""Add the ``plan_rank`` column to CRM Action for multi-action Next Best Action.

One Next Best Action analysis can now emit up to three distinct, priority-ranked
alternatives. ``plan_rank`` records the rank:

  * ``1`` — the current recommendation (``current_slot = 'CURRENT'``)
  * ``2`` / ``3`` — backlog alternatives from the same analysis, held
    ``state = 'deferred'`` so they stay out of the active worklist and every
    SLA / outcome aggregate
  * ``0`` — a single-action generation (the historical shape, and the default
    for every existing row)

Idempotent / re-runnable: the column add is guarded on
``information_schema.columns`` and the default backfills existing rows to ``0``.

Rollback:
  ``ALTER TABLE `tabCRM Action` DROP COLUMN `plan_rank`;``
"""

import frappe

_TABLE = "tabCRM Action Item"
_COLUMN = "plan_rank"


def execute():
	if not frappe.db.table_exists("CRM Action Item"):
		return

	frappe.reload_doc("fcrm", "doctype", "crm_action_item")

	if not _column_exists():
		frappe.db.sql_ddl(
			f"ALTER TABLE `{_TABLE}` ADD COLUMN `{_COLUMN}` int NOT NULL DEFAULT 0"
		)

	# `ADD COLUMN ... DEFAULT 0` already fills existing rows; this only repairs a
	# NULL left by a partially applied earlier run.
	frappe.db.sql(f"UPDATE `{_TABLE}` SET `{_COLUMN}` = 0 WHERE `{_COLUMN}` IS NULL")

	if not frappe.flags.in_test:
		frappe.db.commit()


def _column_exists() -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() "
			"AND table_name = %s AND column_name = %s LIMIT 1",
			(_TABLE, _COLUMN),
		)
	)
