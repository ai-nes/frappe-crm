import frappe


def execute():
	school_types = [
		{"name": "kv1", "school_type_name": "KV1"},
		{"name": "kv2", "school_type_name": "KV2"},
		{"name": "kv2_nt", "school_type_name": "KV2-NT"},
		{"name": "kv3", "school_type_name": "KV3"},
	]
	for st in school_types:
		if not frappe.db.exists("CRM School Type", st["name"]):
			frappe.get_doc({"doctype": "CRM School Type", **st}).insert(ignore_permissions=True)
	frappe.db.commit()
