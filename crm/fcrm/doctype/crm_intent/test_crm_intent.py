import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMIntent(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._ensure_master_data()

	def tearDown(self):
		for name in frappe.db.get_all("CRM Intent", filters={"intent_type": "MAJOR_INQUIRY"}, pluck="name"):
			frappe.delete_doc("CRM Intent", name, force=True)
		for name in frappe.db.get_all(
			"CRM Interaction", filters={"summary": ["like", "_Test Intent Trash%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Interaction", name, force=True)
		for name in frappe.db.get_all(
			"CRM Student", filters={"student_name": ["like", "_Test Intent Trash%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Student", name, force=True)

	def _ensure_master_data(self):
		if not frappe.db.exists("CRM Interaction Type", "OUTREACH"):
			frappe.get_doc(
				{
					"doctype": "CRM Interaction Type",
					"code": "OUTREACH",
					"display_name": "OUTREACH",
				}
			).insert(ignore_permissions=True)

	def _make_student(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": "_Test Intent Trash Student",
				"phone": "0901234599",
			}
		)
		previous_intake_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_intake_flag
		return student

	def _make_interaction(self, student):
		interaction = frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"student": student.name,
				"interaction_type": "OUTREACH",
				"summary": "_Test Intent Trash discussion",
			}
		)
		interaction.insert(ignore_permissions=True)
		return interaction

	def test_deleting_intent_bumps_score_input_revision(self):
		student = self._make_student()
		interaction = self._make_interaction(student)
		intent = frappe.get_doc(
			{
				"doctype": "CRM Intent",
				"interaction": interaction.name,
				"intent_type": "MAJOR_INQUIRY",
				"confidence": 70,
			}
		)
		intent.insert(ignore_permissions=True)
		before_revision = frappe.db.get_value("CRM Student", student.name, "score_input_revision") or 0

		frappe.delete_doc("CRM Intent", intent.name, force=True)

		after_revision = frappe.db.get_value("CRM Student", student.name, "score_input_revision") or 0
		self.assertGreater(after_revision, before_revision)
