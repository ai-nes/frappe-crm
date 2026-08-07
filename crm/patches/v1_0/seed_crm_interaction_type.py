import frappe

INTERACTION_TYPES = ["Tin nhắn Chatwoot", "Cuộc gọi", "Email", "Gặp trực tiếp"]


def execute():
	for name in INTERACTION_TYPES:
		if not frappe.db.exists("CRM Interaction Type", name):
			frappe.get_doc({
				"doctype": "CRM Interaction Type",
				"interaction_type_name": name,
			}).insert(ignore_permissions=True)
