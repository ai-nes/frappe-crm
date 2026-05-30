import json

import frappe


def execute():
	if frappe.db.exists("CRM Fields Layout", {"dt": "Enrollment Student", "type": "Side Panel"}):
		return

	sections = [
		{
			"name": "contact_section",
			"label": "Thông tin liên hệ",
			"opened": True,
			"columns": [{"fields": ["contact", "mobile_no", "email"]}],
		},
		{
			"name": "enrollment_section",
			"label": "Thông tin học vụ",
			"opened": True,
			"columns": [{"fields": ["major", "branch", "enrollment_date", "high_school", "source_lead"]}],
		},
	]

	frappe.get_doc(
		{
			"doctype": "CRM Fields Layout",
			"dt": "Enrollment Student",
			"type": "Side Panel",
			"layout": json.dumps(sections),
		}
	).insert(ignore_permissions=True)
