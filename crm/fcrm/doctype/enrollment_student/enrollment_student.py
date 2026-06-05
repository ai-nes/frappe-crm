import frappe
from frappe import _
from frappe.model.document import Document


class EnrollmentStudent(Document):
	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Student Name",
				"type": "Data",
				"key": "student_name",
				"width": "16rem",
			},
			{
				"label": "Mobile",
				"type": "Data",
				"key": "mobile_no",
				"width": "10rem",
			},
			{
				"label": "Email",
				"type": "Data",
				"key": "email",
				"width": "14rem",
			},
			{
				"label": "Enrollment Status",
				"type": "Select",
				"key": "enrollment_status",
				"width": "12rem",
			},
			{
				"label": "Source",
				"type": "Link",
				"key": "source",
				"options": "CRM Lead Source",
				"width": "10rem",
			},
			{
				"label": "Last Modified",
				"type": "Datetime",
				"key": "modified",
				"width": "8rem",
			},
		]
		rows = [
			"name",
			"student_name",
			"mobile_no",
			"email",
			"enrollment_status",
			"source",
			"converted",
			"modified",
		]
		return {"columns": columns, "rows": rows}


@frappe.whitelist()
def convert_to_contact(student_name):
	student = frappe.get_doc("Enrollment Student", student_name)

	if student.converted:
		existing_contact = frappe.db.get_value("CRM Contact", {"student": student.name}, "name")
		if existing_contact:
			return existing_contact

	staff_name = frappe.db.get_value("Staff", {"user": frappe.session.user}, "name")

	contact = frappe.get_doc({
		"doctype": "CRM Contact",
		"full_name": student.student_name,
		"phone": student.mobile_no,
		"email": student.email,
		"high_school": student.high_school,
		"major": student.major,
		"source": student.source,
		"student": student.name,
		"assigned_to": staff_name,
		"stage": "Interested",
	})
	contact.insert(ignore_permissions=True)

	student.db_set("converted", 1)
	student.db_set("enrollment_status", "Converted")

	return contact.name


@frappe.whitelist()
def create_from_contact(contact):
	contact_doc = frappe.get_doc("Contact", contact)

	if not contact_doc.has_permission("read"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	if not frappe.has_permission("Enrollment Student", "create"):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	student = frappe.get_doc({
		"doctype": "Enrollment Student",
		"student_name": contact_doc.full_name or contact_doc.name,
		"mobile_no": contact_doc.mobile_no,
		"email": contact_doc.email_id,
		"enrollment_status": "Pending Confirmation",
	})
	student.insert()
	return student.name
