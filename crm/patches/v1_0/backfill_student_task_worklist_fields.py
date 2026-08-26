"""Backfill CRM Student Task worklist/decision fields from the linked legacy
CRM Recommendation row created by the retired dual-write in
upsert_student_next_task(). Forward-only and idempotent — safe to re-run."""

import frappe


def execute():
	if not frappe.db.table_exists("CRM Recommendation"):
		return
	for doctype in (
		"crm_student_task",
		"crm_sales_action",
		"crm_student_decision_event",
		"crm_student_command_receipt",
	):
		frappe.reload_doc("fcrm", "doctype", doctype)
	frappe.db.sql(
		"""
		UPDATE `tabCRM Student Task` task
		INNER JOIN `tabCRM Recommendation` rec ON rec.name = task.recommendation
		SET
			task.priority = rec.priority,
			task.worklist_priority_rank = rec.worklist_priority_rank,
			task.revisit_at = rec.revisit_at,
			task.decision_reason = rec.decision_reason,
			task.decision_actor = rec.decision_actor,
			task.decision_at = rec.decision_at,
			task.decision_revision = rec.decision_revision
		WHERE task.recommendation IS NOT NULL AND task.recommendation != ''
		  AND (task.decision_at IS NULL AND (task.decision_revision IS NULL OR task.decision_revision = 0))
		"""
	)
