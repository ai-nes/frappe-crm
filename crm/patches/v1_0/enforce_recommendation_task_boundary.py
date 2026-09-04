"""Additive links, uniqueness and backfill for the recommendation/Task boundary.

Adds the decision-projection columns to ``tabCRM Recommendation``, the source
decision-event link and Action Definition digest to ``tabCRM Action Item``, and
the operation / revision / digest / override columns to
``tabCRM Student Decision Event``. Introduces a single-Task-per-Recommendation
uniqueness rule as ``UNIQUE (recommendation)`` on ``tabCRM Action Item``:
MariaDB treats NULL tuples as distinct so manual and legacy Task rows with no
recommendation are unaffected.

Pre-existing rows that already violate the new rule (more than one Task per
Recommendation) are reconciled before the index is added: the earliest-created
Task keeps the link, the rest have their ``recommendation`` cleared and are
tagged in ``producer_identity`` with an explicit compatibility origin so the
history is not silently rewritten as accepted AI advice.

Backfill is otherwise read-only: every accepted Recommendation that already has
exactly one Task gets ``linked_task`` set and, when blank, a compatibility
``decision_operation = 'ACCEPT'`` with ``decided_at`` copied from the Task's
``accepted_at``.

Idempotent: every column and index change is guarded on ``information_schema``.

Rollback:
  ``ALTER TABLE `tabCRM Action Item` DROP INDEX `crm_action_item_recommendation_uniq`,
    DROP COLUMN `source_decision_event`, DROP COLUMN `action_definition_digest`;``
  ``ALTER TABLE `tabCRM Recommendation` DROP COLUMN `decision_operation`,
    DROP COLUMN `decided_at`, DROP COLUMN `decided_by`,
    DROP COLUMN `source_decision_event`, DROP COLUMN `linked_task`;``
  ``ALTER TABLE `tabCRM Student Decision Event` DROP COLUMN `decision_operation`,
    DROP COLUMN `action_definition_revision`, DROP COLUMN `action_definition_digest`,
    DROP COLUMN `manual_override`;``
"""

import frappe

_ACTION_ITEM_TABLE = "tabCRM Action Item"
_RECOMMENDATION_TABLE = "tabCRM Recommendation"
_DECISION_EVENT_TABLE = "tabCRM Student Decision Event"
_UNIQUE_INDEX = "crm_action_item_recommendation_uniq"
_COMPAT_ORIGIN = "compat:pre-boundary-duplicate"

_ACTION_ITEM_COLUMNS = {
	"source_decision_event": "varchar(140) NULL",
	"action_definition_digest": "varchar(140) NULL",
}
_RECOMMENDATION_COLUMNS = {
	"decision_operation": "varchar(140) NULL",
	"decided_at": "datetime(6) NULL",
	"decided_by": "varchar(140) NULL",
	"source_decision_event": "varchar(140) NULL",
	"linked_task": "varchar(140) NULL",
}
_DECISION_EVENT_COLUMNS = {
	"decision_operation": "varchar(140) NULL",
	"action_definition_revision": "varchar(140) NULL",
	"action_definition_digest": "varchar(140) NULL",
	"manual_override": "int(1) NOT NULL DEFAULT 0",
}


def execute():
	if not frappe.db.table_exists("CRM Action Item") or not frappe.db.table_exists("CRM Recommendation"):
		return

	for doctype in ("crm_action_item", "crm_recommendation", "crm_student_decision_event"):
		frappe.reload_doc("fcrm", "doctype", doctype)

	_add_columns(_ACTION_ITEM_TABLE, _ACTION_ITEM_COLUMNS)
	_add_columns(_RECOMMENDATION_TABLE, _RECOMMENDATION_COLUMNS)
	if frappe.db.table_exists("CRM Student Decision Event"):
		_add_columns(_DECISION_EVENT_TABLE, _DECISION_EVENT_COLUMNS)

	_reconcile_duplicate_tasks()
	_add_unique_index()
	_backfill_decision_projection()

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


def _index_exists(table: str, index_name: str) -> bool:
	return bool(
		frappe.db.sql(
			"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
			"AND table_name = %s AND index_name = %s LIMIT 1",
			(table, index_name),
		)
	)


def _reconcile_duplicate_tasks() -> None:
	"""Keep the earliest Task per Recommendation; detach and tag the rest."""
	if _index_exists(_ACTION_ITEM_TABLE, _UNIQUE_INDEX):
		return
	duplicates = frappe.db.sql(
		"""
		SELECT recommendation, COUNT(*) AS n
		FROM `tabCRM Action Item`
		WHERE recommendation IS NOT NULL AND recommendation != ''
		GROUP BY recommendation
		HAVING n > 1
		""",
		as_dict=True,
	)
	for row in duplicates:
		names = frappe.get_all(
			"CRM Action Item",
			filters={"recommendation": row.recommendation},
			order_by="creation asc",
			pluck="name",
		)
		for stale in names[1:]:
			frappe.db.set_value(
				"CRM Action Item",
				stale,
				{"recommendation": None, "producer_identity": _COMPAT_ORIGIN},
				update_modified=False,
			)
		frappe.logger("crm.decision").warning(
			f"recommendation {row.recommendation} had {row.n} tasks; kept {names[0]}, detached {names[1:]}"
		)


def _add_unique_index() -> None:
	if not _column_exists(_ACTION_ITEM_TABLE, "recommendation"):
		return
	if _index_exists(_ACTION_ITEM_TABLE, _UNIQUE_INDEX):
		return
	frappe.db.sql_ddl(
		f"ALTER TABLE `{_ACTION_ITEM_TABLE}` ADD UNIQUE INDEX `{_UNIQUE_INDEX}` (`recommendation`)"
	)


def _backfill_decision_projection() -> None:
	rows = frappe.db.sql(
		"""
		SELECT r.name AS recommendation, r.decision_status, r.linked_task, r.decision_operation,
		       a.name AS task, a.accepted_at
		FROM `tabCRM Recommendation` r
		JOIN `tabCRM Action Item` a ON a.recommendation = r.name
		WHERE (r.linked_task IS NULL OR r.linked_task = '')
		""",
		as_dict=True,
	)
	for row in rows:
		values = {"linked_task": row.task}
		if row.decision_status == "accepted" and not row.decision_operation:
			values["decision_operation"] = "ACCEPT"
			values["decided_at"] = row.accepted_at
		frappe.db.set_value("CRM Recommendation", row.recommendation, values, update_modified=False)
