"""Initial controlled vocabulary from the supplied FAIP Need/Tag trees."""

CATALOG = {
	"need": {
		"NEED_CONTACT": "FIRST_CONTACT FOLLOW_UP CALLBACK",
		"NEED_INFORMATION": "PROGRAM_INFORMATION ADMISSION_INFORMATION TUITION_INFORMATION SCHOLARSHIP_INFORMATION CAREER_INFORMATION",
		"NEED_ENGAGEMENT": "COUNSELING EVENT_ENGAGEMENT CAMPUS_EXPERIENCE",
		"NEED_APPLICATION": "APPLICATION_GUIDANCE APPLICATION_INCOMPLETE DOCUMENT_SUPPORT APPLICATION_DEADLINE",
		"NEED_CONVERSION": "DECISION_SUPPORT ENROLLMENT_SUPPORT FINANCIAL_SUPPORT",
		"NEED_PARENT": "PARENT_ENGAGEMENT PARENT_COUNSELING",
		"NEED_RECOVERY": "RE_ENGAGEMENT NO_RESPONSE NOT_READY",
	},
	"tag": {
		"ATTENTION": "VIP HIGH_PRIORITY SPECIAL_ATTENTION",
		"RELATIONSHIP": "PARENT_INVOLVED PARENT_DECISION_MAKER OTHER_DECISION_MAKER",
		"CONTEXT": "SPECIAL_CASE HARD_TO_REACH SPECIAL_REQUIREMENT",
		"OPERATIONAL": "MANUAL_REVIEW SPECIAL_HANDLING ESCALATED",
	},
}


def seed_catalog():
	import frappe

	if not frappe.db.exists("DocType", "CRM Need") or not frappe.db.exists("DocType", "CRM Tag"):
		return
	for kind, groups in CATALOG.items():
		doctype = "CRM Need" if kind == "need" else "CRM Tag"
		for group, codes in groups.items():
			for code in codes.split():
				if not frappe.db.exists(doctype, {"code": code}):
					frappe.get_doc(
						{
							"doctype": doctype,
							"code": code,
							"label": code.replace("_", " ").title(),
							"group_name": group,
							"status": "draft",
						}
					).insert(ignore_permissions=True)
