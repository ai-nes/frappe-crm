import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMInteraction(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._ensure_master_data()

	def tearDown(self):
		for name in frappe.db.get_all("CRM Intent", filters={"intent_type": "_Test Tuition Inquiry"}, pluck="name"):
			frappe.delete_doc("CRM Intent", name, force=True)
		for name in frappe.db.get_all("CRM Interaction", filters={"summary": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Interaction", name, force=True)
		for name in frappe.db.get_all("CRM Student", filters={"student_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Student", name, force=True)

	def _ensure_master_data(self):
		if not frappe.db.exists("CRM Interaction Type", "_Test Phone Call"):
			frappe.get_doc({
				"doctype": "CRM Interaction Type",
				"interaction_type_name": "_Test Phone Call",
			}).insert(ignore_permissions=True)

		if not frappe.db.exists("CRM Intent Type", "_Test Tuition Inquiry"):
			frappe.get_doc({
				"doctype": "CRM Intent Type",
				"intent_type_name": "_Test Tuition Inquiry",
				"importance": "Very High",
			}).insert(ignore_permissions=True)

	def _make_student(self):
		student = frappe.get_doc({
			"doctype": "CRM Student",
			"student_name": "_Test Interaction Student",
			"phone": "0901234567",
		})
		student.insert(ignore_permissions=True)
		return student

	def _make_interaction(self, student):
		interaction = frappe.get_doc({
			"doctype": "CRM Interaction",
			"student": student.name,
			"interaction_type": "_Test Phone Call",
			"summary": "_Test discussed tuition",
		})
		interaction.insert(ignore_permissions=True)
		return interaction

	def test_interaction_defaults_datetime(self):
		student = self._make_student()
		interaction = self._make_interaction(student)

		self.assertEqual(interaction.student, student.name)
		self.assertTrue(interaction.interaction_datetime)

	def test_intent_snapshots_student_and_importance(self):
		student = self._make_student()
		interaction = self._make_interaction(student)

		intent = frappe.get_doc({
			"doctype": "CRM Intent",
			"interaction": interaction.name,
			"intent_type": "_Test Tuition Inquiry",
			"confidence": 80,
		})
		intent.insert(ignore_permissions=True)

		self.assertEqual(intent.student, student.name)
		self.assertEqual(intent.importance, "Very High")
