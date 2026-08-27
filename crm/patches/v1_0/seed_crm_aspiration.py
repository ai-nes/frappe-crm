import frappe


def execute():
	default_aspirations = [
		"Undecided",
		"NV1",
		"NV2",
		"NV3",
		"NV4",
		"NV5",
		"NV6",
		"Not Applying to FPT",
	]

	for name in default_aspirations:
		if not frappe.db.exists("CRM Term", {"term_name": name, "category": "aspiration"}):
			frappe.get_doc({
				"doctype": "CRM Term", "term_name": name, "category": "aspiration",
			}).insert(ignore_permissions=True)

	frappe.db.commit()
