import frappe


def execute():
	for student in frappe.get_all("CRM Lead", filters={"converted": 1}, pluck="name"):
		if not frappe.db.exists("CRM Student", {"student": student}):
			frappe.db.set_value("CRM Lead", student, "converted", 0)
