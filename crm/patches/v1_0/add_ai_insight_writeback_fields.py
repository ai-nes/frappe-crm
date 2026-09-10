"""Ensure AI Insight write-back fields are loaded during migration."""

import frappe


def _ensure_index(doctype: str, fields: tuple[str, ...], index_name: str):
	if not frappe.db.table_exists(doctype):
		return
	if frappe.db.sql(
		"SELECT 1 FROM information_schema.statistics "
		"WHERE table_schema = DATABASE() AND table_name = %s AND index_name = %s LIMIT 1",
		(f"tab{doctype}", index_name),
	):
		return
	columns = ", ".join(f"`{field}`" for field in fields)
	frappe.db.sql_ddl(f"ALTER TABLE `tab{doctype}` ADD INDEX `{index_name}` ({columns})")


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_ai_student_insight")
	frappe.reload_doc("fcrm", "doctype", "crm_ai_student_insight_item")
	frappe.reload_doc("fcrm", "doctype", "crm_student_command_receipt")
	_ensure_index(
		"CRM AI Student Insight",
		("student", "insight_type", "ai_generated_at"),
		"crm_ai_student_insight_student_type_idx",
	)
