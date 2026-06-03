import frappe
from frappe import _
from frappe.model.document import Document


class EnrollmentStudent(Document):
	pass


@frappe.whitelist()
def convert_to_contact(student_name):
	student = frappe.get_doc("Enrollment Student", student_name)

	if student.converted:
		frappe.throw(
			frappe._("Student {0} has already been converted to a CRM Contact.").format(student_name),
			frappe.ValidationError,
		)

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
		"enrollment_status": "Chờ xác nhận",
	})
	student.insert()
	return student.name
