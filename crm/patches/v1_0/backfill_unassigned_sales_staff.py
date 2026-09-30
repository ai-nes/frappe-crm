import frappe

from crm.fcrm.staff_provisioning import ensure_sales_staff


def execute():
	existing = set(frappe.get_all("CRM Staff", pluck="user", limit_page_length=0))
	created = []
	for user in frappe.get_all("User", filters={"enabled": 1}, pluck="name", limit_page_length=0):
		if user not in existing:
			staff = ensure_sales_staff(frappe.get_doc("User", user))
			if staff:
				created.append(staff)
	return created
