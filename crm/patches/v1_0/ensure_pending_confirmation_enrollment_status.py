import frappe


def execute():
	if not frappe.db.exists("DocType", "CRM Enrollment Status"):
		return
	if not frappe.db.exists("CRM Enrollment Status", "Pending Confirmation"):
		frappe.get_doc({
			"doctype": "CRM Enrollment Status",
			"status_name": "Pending Confirmation",
		}).insert(ignore_permissions=True)
