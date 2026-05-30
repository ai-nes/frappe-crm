# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class EnrollmentStudent(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		branch: DF.Link | None
		contact: DF.Link | None
		email: DF.Data | None
		enrollment_date: DF.Date | None
		enrollment_status: DF.Literal["Chờ xác nhận", "Đã nhập học", "Bảo lưu", "Thôi học"]
		high_school: DF.Link | None
		import_source_id: DF.Int
		major: DF.Link | None
		mobile_no: DF.Data | None
		source_lead: DF.Link | None
		student_name: DF.Data
	# end: auto-generated types

	pass


@frappe.whitelist()
def create_from_contact(contact, branch=None, major=None, enrollment_date=None):
	frappe.has_permission("Contact", "read", contact, throw=True)
	if not frappe.has_permission("Enrollment Student", "create"):
		frappe.throw(frappe._("Not permitted to create Enrollment Student"))
	contact_doc = frappe.get_doc("Contact", contact)
	student_name = f"{contact_doc.last_name or ''} {contact_doc.first_name or ''}".strip()
	if not student_name:
		frappe.throw("Contact has no name set.")
	student = frappe.get_doc({
		"doctype": "Enrollment Student",
		"student_name": student_name,
		"mobile_no": contact_doc.mobile_no,
		"email": contact_doc.email_id,
		"contact": contact,
		"source_lead": contact_doc.source_lead,
		"high_school": contact_doc.school,
		"major": major or contact_doc.major,
		"branch": branch,
		"enrollment_status": "Chờ xác nhận",
		"enrollment_date": enrollment_date,
	})
	student.insert(ignore_permissions=True)
	return student.name
