"""Backfill legacy Student Task fields when upgrading an older site.

The intermediate DocType may already have been removed on a fresh install;
in that case this historical patch is a no-op.
"""

import frappe


def execute():
	if not frappe.db.table_exists("CRM Recommendation") or not frappe.db.table_exists("CRM Student Task"):
		return
	frappe.reload_doc("fcrm", "doctype", "crm_student_decision_event")
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
