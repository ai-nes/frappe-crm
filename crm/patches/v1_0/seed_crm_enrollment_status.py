import frappe

STATUSES = ["Mới", "Có triển vọng", "Đã xác nhận", "Đã nhập học", "Đã chuyển đổi", "Từ chối"]


def execute():
	for name in STATUSES:
		if not frappe.db.exists("CRM Enrollment Status", name):
			frappe.get_doc({
				"doctype": "CRM Enrollment Status",
				"status_name": name,
			}).insert(ignore_permissions=True)
