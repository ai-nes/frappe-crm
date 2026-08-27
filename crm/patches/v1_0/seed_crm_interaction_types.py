"""Phase 4: seed the standard CRM Interaction Type master list defined by the
admissions operating model, so production interactions are always created
against one of these instead of an ad-hoc arbitrary type.
"""

import frappe

INTERACTION_TYPES = [
	"Lead Captured",
	"MQL Qualified",
	"MQL Rejected",
	"Lead Assigned",
	"Lead Reassigned",
	"Outreach",
	"Connected",
	"Counseling",
	"Stage Changed",
	"Application Submitted",
	"Admitted",
	"Enrollment Confirmed",
	"Registered",
	"Checked-in",
	"No-show",
	"Feedback",
	"Opt-in",
	"Opt-out",
	"Bounce",
	"Data Error",
]


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_interaction", force=True)

	for interaction_type_name in INTERACTION_TYPES:
		if not frappe.db.exists("CRM Term", {"term_name": interaction_type_name, "category": "interaction_type"}):
			frappe.get_doc({
				"doctype": "CRM Term", "term_name": interaction_type_name, "category": "interaction_type",
			}).insert(ignore_permissions=True)
