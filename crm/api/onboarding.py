import frappe


@frappe.whitelist()
def get_first_crm_student():
	student = frappe.get_list(
		"CRM Student",
		filters={"converted": 0},
		fields=["name"],
		order_by="creation",
		limit_page_length=1,
	)
	return student[0].name if student else None


@frappe.whitelist()
def get_first_crm_contact():
	contact = frappe.get_list(
		"CRM Contact",
		fields=["name"],
		order_by="creation",
		limit_page_length=1,
	)
	return contact[0].name if contact else None
