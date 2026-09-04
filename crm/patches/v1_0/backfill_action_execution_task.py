"""Rebind Action Execution and Recommendation Feedback onto the accepted Task.

``CRM Action Execution`` and ``CRM Recommendation Feedback`` gain an explicit
``task`` (``CRM Action Item``) link. Historically an execution was reachable
only through its ``recommendation``; the Task is the canonical admissions work
item, so the operational reader now follows the Task directly.

Backfill is deterministic and idempotent:
  * execution ``task`` <- the ``action`` of the attempt that owns the execution
  * feedback ``task``  <- the ``task`` of the execution behind the outcome

Only rows with a null ``task`` are touched, so re-running is a no-op. Rows with
no attempt / execution keep a null link and are simply not Task-indexed.

Rollback:
  ``ALTER TABLE `tabCRM Action Execution` DROP COLUMN task;``
  ``ALTER TABLE `tabCRM Recommendation Feedback` DROP COLUMN task;``
"""

import frappe

_EXECUTION_TABLE = "tabCRM Action Execution"
_FEEDBACK_TABLE = "tabCRM Recommendation Feedback"
_EXECUTION_TASK_INDEX = "crm_action_execution_task_idx"
_FEEDBACK_TASK_INDEX = "crm_recommendation_feedback_task_idx"


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_action_execution")
	frappe.reload_doc("fcrm", "doctype", "crm_recommendation_feedback")

	if frappe.db.table_exists("CRM Action Execution") and frappe.db.table_exists(
		"CRM Action Execution Attempt"
	):
		frappe.db.sql(
			"""
			UPDATE `tabCRM Action Execution` e
			JOIN `tabCRM Action Execution Attempt` a ON a.nba_execution = e.name
			SET e.task = a.action
			WHERE (e.task IS NULL OR e.task = '') AND a.action IS NOT NULL AND a.action != ''
			"""
		)
		_ensure_index(_EXECUTION_TABLE, _EXECUTION_TASK_INDEX, "task")

	if frappe.db.table_exists("CRM Recommendation Feedback") and frappe.db.table_exists(
		"CRM Action Execution"
	):
		frappe.db.sql(
			"""
			UPDATE `tabCRM Recommendation Feedback` f
			JOIN `tabCRM Action Outcome` o ON o.name = f.outcome
			JOIN `tabCRM Action Execution` e ON e.name = o.execution
			SET f.task = e.task
			WHERE (f.task IS NULL OR f.task = '') AND e.task IS NOT NULL AND e.task != ''
			"""
		)
		_ensure_index(_FEEDBACK_TABLE, _FEEDBACK_TASK_INDEX, "task")

	if not frappe.flags.in_test:
		frappe.db.commit()


def _ensure_index(table: str, index_name: str, column: str) -> None:
	exists = frappe.db.sql(
		"SELECT 1 FROM information_schema.statistics WHERE table_schema = DATABASE() "
		"AND table_name = %s AND index_name = %s LIMIT 1",
		(table, index_name),
	)
	if not exists:
		frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD INDEX `{index_name}` (`{column}`)")
