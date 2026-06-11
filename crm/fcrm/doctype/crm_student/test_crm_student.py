import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.doctype.crm_student.crm_student import (
	convert_to_contact,
	create_from_contact,
)


class TestCRMStudent(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _make_student(self, name="_Test Convert Student"):
		if frappe.db.exists("CRM Student", name):
			frappe.delete_doc("CRM Student", name, force=True)
		student = frappe.get_doc({
			"doctype": "CRM Student",
			"student_name": name,
			"mobile_no": "0901234567",
			"email": "test.convert@example.com",
			"enrollment_status": "Pending Confirmation",
		})
		student.insert(ignore_permissions=True)
		return student

	def tearDown(self):
		for name in frappe.db.get_all("CRM Student", filters={"student_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)
		for name in frappe.db.get_all("CRM Contact", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("Contact", filters={"first_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("Contact", name, force=True)

	def test_convert_creates_crm_contact(self):
		student = self._make_student()
		contact_name = convert_to_contact(student.name)

		contact = frappe.get_doc("CRM Contact", contact_name)
		self.assertEqual(contact.full_name, student.student_name)
		self.assertEqual(contact.phone, student.mobile_no)
		self.assertEqual(contact.email, student.email)
		self.assertEqual(contact.student, student.name)
		self.assertEqual(contact.stage, "Interested")

		student.reload()
		self.assertEqual(student.converted, 1)
		self.assertEqual(student.enrollment_status, "Converted")

	def test_convert_double_conversion_returns_existing_contact(self):
		student = self._make_student("_Test Double Convert Student")
		contact_name = convert_to_contact(student.name)

		self.assertEqual(convert_to_contact(student.name), contact_name)

	def test_student_mobile_no_syncs_to_linked_crm_contact_phone(self):
		student = self._make_student("_Test Student Phone Sync")
		contact_name = convert_to_contact(student.name)

		student.mobile_no = "0907654321"
		student.save(ignore_permissions=True)

		contact = frappe.get_doc("CRM Contact", contact_name)
		self.assertEqual(contact.phone, "0907654321")

	def test_crm_contact_phone_syncs_to_student_mobile_no(self):
		student = self._make_student("_Test Contact Phone Sync")
		contact_name = convert_to_contact(student.name)

		contact = frappe.get_doc("CRM Contact", contact_name)
		contact.phone = "0902222333"
		contact.save(ignore_permissions=True)

		student.reload()
		self.assertEqual(student.mobile_no, "0902222333")

	def test_create_from_contact_creates_crm_student(self):
		contact = frappe.get_doc({
			"doctype": "Contact",
			"first_name": "_Test",
			"last_name": "Source Contact",
			"email_id": "test.source@example.com",
			"mobile_no": "0912345678",
		})
		contact.insert(ignore_permissions=True)

		student_name = create_from_contact(contact.name)
		student = frappe.get_doc("CRM Student", student_name)

		self.assertEqual(student.student_name, contact.full_name)
		self.assertEqual(student.mobile_no, contact.mobile_no)
		self.assertEqual(student.email, contact.email_id)
