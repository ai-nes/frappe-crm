"""Grant CTV Sale read access to scoped Student work items."""

import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Action Item"):
		return
	criteria = {
		"parent": "CRM Action Item",
		"parenttype": "DocType",
		"role": "CTV Sale",
		"permlevel": 0,
	}
	name = frappe.db.get_value("DocPerm", criteria, "name")
	if name:
		doc = frappe.get_doc("DocPerm", name)
		permission_flags = {"read": 1, "write": 0, "create": 0, "delete": 0, "export": 0}
		for fieldname, value in permission_flags.items():
			doc.set(fieldname, value)
		doc.save(ignore_permissions=True)
		frappe.clear_cache(doctype="CRM Action Item")
		return
	frappe.get_doc(
		{
			"doctype": "DocPerm",
			"parent": "CRM Action Item",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"permlevel": 0,
			"role": "CTV Sale",
			"read": 1,
			"write": 0,
			"create": 0,
			"delete": 0,
			"export": 0,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="CRM Action Item")
