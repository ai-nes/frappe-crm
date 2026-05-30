# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestEnrollmentStudent(FrappeTestCase):
	def test_create_enrollment_student(self):
		student = frappe.get_doc(
			{
				"doctype": "Enrollment Student",
				"student_name": "_Test Student",
				"enrollment_status": "Chờ xác nhận",
			}
		)
		student.insert(ignore_permissions=True)
		self.assertEqual(student.enrollment_status, "Chờ xác nhận")
		student.delete()
