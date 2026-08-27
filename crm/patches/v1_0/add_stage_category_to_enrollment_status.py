"""
Add stage_category (open/enrolled/lost) to CRM Enrollment Status and backfill
the 6 canonical statuses seeded by fix_enrollment_status_cleanup — this is the
single source of truth crm-agents' lead scoring reads to determine which
enrollment statuses are terminal.
"""

import frappe

STAGE_CATEGORY_MAP = {
	"Mới": "open",
	"Có triển vọng": "open",
	"Đã xác nhận": "open",
	"Đã nhập học": "enrolled",
	"Đã chuyển đổi": "open",
	"Từ chối": "lost",
}


def execute():
	if not frappe.db.exists("DocType", "CRM Enrollment Status"):
		return
	frappe.reload_doc("fcrm", "doctype", "crm_enrollment_status", force=True)

	for status_name, stage_category in STAGE_CATEGORY_MAP.items():
		if frappe.db.exists("CRM Enrollment Status", status_name):
			frappe.db.set_value("CRM Enrollment Status", status_name, "stage_category", stage_category)

	# Any status outside the canonical map (custom additions) defaults to "open"
	# rather than being left blank, since stage_category is a required field.
	frappe.db.sql(
		"UPDATE `tabCRM Enrollment Status` SET stage_category = 'open' WHERE stage_category IS NULL OR stage_category = ''"
	)

	frappe.clear_cache(doctype="CRM Enrollment Status")
