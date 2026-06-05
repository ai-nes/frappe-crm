import frappe


def execute():
	for student in frappe.get_all("CRM Student", filters={"converted": 1}, pluck="name"):
		if not frappe.db.exists("CRM Contact", {"student": student}):
			frappe.db.set_value("CRM Student", student, "converted", 0)
