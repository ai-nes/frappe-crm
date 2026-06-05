import json
import os

import frappe
from frappe.tests.utils import FrappeTestCase


class TestDemoData(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from crm.demo.api import clear_demo_data

		clear_demo_data()

	def _check_demo_records_exist(self, doctype, record_names):
		if not record_names:
			return False
		return any(frappe.db.exists(doctype, name) for name in record_names)

	def test_demo_data_lifecycle(self):
		from crm.demo.api import clear_demo_data, create_demo_data
		from crm.demo.users import DEMO_USERS

		demo_state_key = "crm_demo_data_created"
		demo_students_key = "crm_demo_students"
		demo_contacts_key = "crm_demo_crm_contacts"
		demo_notes_key = "crm_demo_notes"
		demo_tasks_key = "crm_demo_tasks"
		demo_call_logs_key = "crm_demo_call_logs"

		for user in DEMO_USERS:
			self.assertFalse(frappe.db.exists("User", user["email"]))

		self.assertIsNone(frappe.db.get_default(demo_students_key))
		self.assertIsNone(frappe.db.get_default(demo_contacts_key))
		self.assertIsNone(frappe.db.get_default(demo_notes_key))
		self.assertIsNone(frappe.db.get_default(demo_tasks_key))
		self.assertIsNone(frappe.db.get_default(demo_call_logs_key))

		create_demo_data()

		for user in DEMO_USERS:
			doc = frappe.get_doc("User", user["email"])
			self.assertEqual(doc.user_image, user["avatar"])
			self.assertTrue(doc.enabled)
			self.assertEqual(doc.first_name, user["first_name"])
			self.assertEqual(doc.last_name, user["last_name"])

		student_names = json.loads(frappe.db.get_default(demo_students_key) or "[]")
		contact_names = json.loads(frappe.db.get_default(demo_contacts_key) or "[]")
		note_names = json.loads(frappe.db.get_default(demo_notes_key) or "[]")
		task_names = json.loads(frappe.db.get_default(demo_tasks_key) or "[]")
		call_log_names = json.loads(frappe.db.get_default(demo_call_logs_key) or "[]")

		self.assertEqual(len(student_names), 3)
		self.assertEqual(len(contact_names), 3)
		self.assertGreater(len(note_names), 0)
		self.assertGreater(len(task_names), 0)
		self.assertGreater(len(call_log_names), 0)

		for student_name in student_names:
			student = frappe.get_doc("CRM Student", student_name)
			self.assertTrue(student.student_name)
			self.assertTrue(student.email)

		for contact_name in contact_names:
			contact = frappe.get_doc("CRM Contact", contact_name)
			self.assertTrue(contact.full_name)
			self.assertIn(contact.stage, ["Interested", "Qualified", "Enrolled"])

		avatar_dir = os.path.abspath(
			os.path.join(os.path.dirname(__file__), "..", "..", "crm", "public", "images", "demo")
		)
		for user in DEMO_USERS:
			filename = user["avatar"].split("/")[-1]
			path = os.path.join(avatar_dir, filename)
			self.assertTrue(os.path.exists(path), f"Missing avatar: {path}")

		self.assertEqual(frappe.db.get_default(demo_state_key), "1")
		self.assertTrue(frappe.db.get_default(demo_students_key))
		self.assertTrue(frappe.db.get_default(demo_contacts_key))
		self.assertTrue(frappe.db.get_default(demo_notes_key))
		self.assertTrue(frappe.db.get_default(demo_tasks_key))
		self.assertTrue(frappe.db.get_default(demo_call_logs_key))

		clear_demo_data()

		for user in DEMO_USERS:
			self.assertFalse(frappe.db.exists("User", user["email"]))

		self.assertFalse(self._check_demo_records_exist("CRM Call Log", call_log_names))
		self.assertFalse(self._check_demo_records_exist("CRM Task", task_names))
		self.assertFalse(self._check_demo_records_exist("FCRM Note", note_names))
		self.assertFalse(self._check_demo_records_exist("CRM Contact", contact_names))
		self.assertFalse(self._check_demo_records_exist("CRM Student", student_names))

		self.assertIsNone(frappe.db.get_default(demo_state_key))
		self.assertIsNone(frappe.db.get_default(demo_students_key))
		self.assertIsNone(frappe.db.get_default(demo_contacts_key))
		self.assertIsNone(frappe.db.get_default(demo_notes_key))
		self.assertIsNone(frappe.db.get_default(demo_tasks_key))
		self.assertIsNone(frappe.db.get_default(demo_call_logs_key))
