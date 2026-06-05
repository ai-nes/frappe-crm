import frappe


@frappe.whitelist()
def get_first_enrollment_student():
	student = frappe.get_all(
		"Enrollment Student",
		filters={"converted": 0},
		fields=["name"],
		order_by="creation",
		limit=1,
	)
	return student[0].name if student else None


@frappe.whitelist()
def get_first_crm_contact():
	contact = frappe.get_all(
		"CRM Contact",
		fields=["name"],
		order_by="creation",
		limit=1,
	)
	return contact[0].name if contact else None
