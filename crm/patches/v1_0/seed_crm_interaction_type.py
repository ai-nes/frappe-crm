import frappe

INTERACTION_TYPES = ["Tin nhắn Chatwoot", "Cuộc gọi", "Email", "Gặp trực tiếp"]


def execute():
	for name in INTERACTION_TYPES:
		if not frappe.db.exists("CRM Term", {"term_name": name, "category": "interaction_type"}):
			frappe.get_doc({
				"doctype": "CRM Term", "term_name": name, "category": "interaction_type",
			}).insert(ignore_permissions=True)
