"""Add lifecycle_stage (Lead/MQL/Applicant/Enrolled/Lost) to CRM Enrollment
Status and backfill the 6 canonical statuses — the Phase 3 two-track model's
mapping from day-to-day working status onto the long-term funnel position.
Locked mapping (5-stage reduced form): SQL and Admitted are folded into
Applicant/Enrolled respectively since the existing statuses don't carry
enough resolution to distinguish them.
"""

import frappe

LIFECYCLE_STAGE_MAP = {
	"Mới": "Lead",
	"Có triển vọng": "MQL",
	"Đã xác nhận": "Applicant",
	"Đã nhập học": "Enrolled",
	"Đã chuyển đổi": "Enrolled",
	"Từ chối": "Lost",
}


def execute():
	if not frappe.db.exists("DocType", "CRM Enrollment Status"):
		return
	frappe.reload_doc("fcrm", "doctype", "crm_enrollment_status", force=True)

	for status_name, lifecycle_stage in LIFECYCLE_STAGE_MAP.items():
		if frappe.db.exists("CRM Enrollment Status", status_name):
			frappe.db.set_value("CRM Enrollment Status", status_name, "lifecycle_stage", lifecycle_stage)

	# Any status outside the canonical map (custom additions) defaults to
	# "Lead" rather than being left blank, since lifecycle_stage is required.
	frappe.db.sql(
		"UPDATE `tabCRM Enrollment Status` SET lifecycle_stage = 'Lead' "
		"WHERE lifecycle_stage IS NULL OR lifecycle_stage = ''"
	)

	frappe.clear_cache(doctype="CRM Enrollment Status")
