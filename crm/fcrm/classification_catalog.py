"""Initial controlled vocabulary from the supplied FAIP Need/Tag trees."""

import frappe

GROUP_CATALOG = {
	"need": {
		"NEED_CONTACT": "Cần liên hệ",
		"NEED_INFORMATION": "Cần thông tin",
		"NEED_ENGAGEMENT": "Cần tương tác",
		"NEED_APPLICATION": "Cần hỗ trợ hồ sơ",
		"NEED_CONVERSION": "Cần hỗ trợ chuyển đổi",
		"NEED_PARENT": "Cần hỗ trợ phụ huynh",
		"NEED_RECOVERY": "Cần phục hồi",
	},
	"tag": {
		"ATTENTION": "Cần chú ý",
		"RELATIONSHIP": "Quan hệ",
		"CONTEXT": "Bối cảnh",
		"OPERATIONAL": "Vận hành",
	},
}

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


def _activate_if_draft(doctype, name):
	if frappe.db.get_value(doctype, name, "status") != "draft":
		return
	revision = frappe.db.get_value(doctype, name, "revision") or 0
	frappe.db.set_value(
		doctype,
		name,
		{"status": "active", "revision": int(revision) + 1},
		update_modified=False,
	)


def seed_catalog():
	if not frappe.db.exists("DocType", "CRM Need") or not frappe.db.exists("DocType", "CRM Tag"):
		return
	for kind, groups in CATALOG.items():
		doctype = "CRM Need" if kind == "need" else "CRM Tag"
		group_doctype = "CRM Need Group" if kind == "need" else "CRM Tag Group"
		for sort_order, (group, codes) in enumerate(groups.items(), start=1):
			if not frappe.db.exists(group_doctype, group):
				frappe.get_doc(
					{
						"doctype": group_doctype,
						"code": group,
						"label": GROUP_CATALOG[kind][group],
						"status": "draft",
						"sort_order": sort_order * 10,
					}
				).insert(ignore_permissions=True)
			_activate_if_draft(group_doctype, group)
			for code in codes.split():
				if not frappe.db.exists(doctype, {"code": code}):
					frappe.get_doc(
						{
							"doctype": doctype,
							"code": code,
							"label": code.replace("_", " ").title(),
							"group": group,
							"group_name": group,
							"status": "draft",
						}
					).insert(ignore_permissions=True)
				_term_name = frappe.db.get_value(doctype, {"code": code}, "name")
				_activate_if_draft(doctype, _term_name)
