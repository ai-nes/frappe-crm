import frappe


NEW_LEAD_SOURCES = ["Google", "Zalo", "TikTok"]

# (platform_name, lead_source family, sub_channel)
PLATFORMS = [
	("Facebook Form", "Facebook", "Form"),
	("Facebook Landing Page", "Facebook", "Landing Page"),
	("Google Form", "Google", "Form"),
	("Google Landing Page", "Google", "Landing Page"),
	("Zalo", "Zalo", ""),
	("TikTok", "TikTok", ""),
	("Referral", "Referral", ""),
	("Website", "Website", ""),
]


def execute():
	if frappe.db.exists("CRM Lead Source", "Reference") and not frappe.db.exists(
		"CRM Lead Source", "Referral"
	):
		frappe.rename_doc("CRM Lead Source", "Reference", "Referral", force=True)

	for source_name in NEW_LEAD_SOURCES:
		if not frappe.db.exists("CRM Lead Source", source_name):
			frappe.get_doc({"doctype": "CRM Lead Source", "source_name": source_name}).insert(
				ignore_permissions=True
			)

	for platform_name, lead_source, sub_channel in PLATFORMS:
		if not frappe.db.exists("CRM Lead Source", lead_source):
			continue
		if not frappe.db.exists("CRM Platform", platform_name):
			frappe.get_doc(
				{
					"doctype": "CRM Platform",
					"platform_name": platform_name,
					"lead_source": lead_source,
					"sub_channel": sub_channel,
				}
			).insert(ignore_permissions=True)

	frappe.db.commit()
