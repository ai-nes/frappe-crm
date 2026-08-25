from frappe.tests.utils import FrappeTestCase

from crm.services.student_next_task_policy import choose_next_task_policy


class TestStudentNextTaskPolicy(FrappeTestCase):
	def test_policy_maps_context_to_governed_action_and_objective(self):
		action, objective, actionable = choose_next_task_policy(
			"application documents", "Consulting", ["DOCUMENT_REQUEST", "CALL"]
		)

		self.assertEqual(action, "DOCUMENT_REQUEST")
		self.assertTrue(actionable)
		self.assertIn("application documents", objective)
		self.assertIn("Consulting", objective)

	def test_parent_contact_requires_authority_and_never_falls_back_to_contact(self):
		action, objective, actionable = choose_next_task_policy(
			"parent contact", "Lead", ["CALL", "EMAIL"], parent_authorized=False
		)

		self.assertIsNone(action)
		self.assertFalse(actionable)
		self.assertIn("Do not contact", objective)

	def test_ineligible_lifecycle_is_monitor_only(self):
		action, objective, actionable = choose_next_task_policy(
			"program information", "Lost", ["CALL", "EMAIL"], eligible=False
		)

		self.assertIsNone(action)
		self.assertFalse(actionable)
		self.assertIn("not eligible", objective)
