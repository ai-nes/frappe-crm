"""Add the optional result digest column to CRM Analysis Run Stage.

Additive and nullable. Existing rows and existing settlement callers are
unaffected; the digest is written only when a worker supplies it.

Rollback: ``ALTER TABLE `tabCRM Analysis Run Stage` DROP COLUMN `result_digest``.
"""

import frappe


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_analysis_run_stage")
	if frappe.db.table_exists("CRM Analysis Run Stage") and not frappe.db.has_column(
		"CRM Analysis Run Stage", "result_digest"
	):
		frappe.db.add_column("CRM Analysis Run Stage", "result_digest", "Data")
