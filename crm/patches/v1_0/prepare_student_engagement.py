"""Prepare bounded Phase 5 event/context indexes.

This patch is deliberately schema-tolerant: a site may run it before one of
the Phase 5 event DocTypes is installed while a staged rollout is in progress.
It adds indexes only when every requested field is deployed and never rewrites
historical Student, Interaction or Task data.
"""

from __future__ import annotations

import frappe


def _columns(doctype: str) -> set[str]:
	try:
		return {"name", *{field.fieldname for field in frappe.get_meta(doctype).fields}}
	except Exception:
		return set()


def _add_index(doctype: str, fields: tuple[str, ...], name: str) -> bool:
	if not frappe.db.table_exists(doctype):
		return False
	if not set(fields) <= _columns(doctype):
		return False
	table = f"tab{doctype}"
	if frappe.db.sql(f"SHOW INDEX FROM `{table}` WHERE Key_name = %s", name):
		return True
	columns = ", ".join(f"`{field}`" for field in fields)
	frappe.db.sql_ddl(f"ALTER TABLE `{table}` ADD INDEX `{name}` ({columns})")
	return True


def execute():
	indexes = (
		("CRM Student Outcome", ("student", "occurred_at", "name"), "crm_student_outcome_student_at_idx"),
		("CRM Student Outcome", ("student", "superseded_by"), "crm_student_outcome_student_superseded_idx"),
		("CRM Student Outcome", ("source_doctype", "source_name"), "crm_student_outcome_source_idx"),
		("CRM Student Lifecycle Event", ("student", "occurred_at", "name"), "crm_student_lifecycle_student_at_idx"),
		("CRM Student Lifecycle Event", ("student", "to_stage", "occurred_at"), "crm_student_lifecycle_student_stage_at_idx"),
		("CRM Interaction", ("student", "interaction_datetime", "name"), "crm_interaction_student_at_idx"),
		("Task", ("reference_doctype", "reference_docname", "status", "due_date"), "crm_task_student_reference_status_due_idx"),
		("Task", ("student", "status", "due_date"), "crm_task_student_status_due_idx"),
	)
	created = []
	skipped = []
	for doctype, fields, name in indexes:
		if _add_index(doctype, fields, name):
			created.append(name)
		else:
			skipped.append(name)
	return {"indexes_ready": created, "indexes_skipped": skipped}
