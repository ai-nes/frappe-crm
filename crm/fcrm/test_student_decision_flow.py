"""Decision/action command boundary tests without mutable fixtures."""

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_decision import ACTION_TRANSITIONS, OUTCOMES, StudentDecisionError, _required


class TestStudentDecisionFlow(FrappeTestCase):
	def test_sales_action_state_machine_has_no_direct_completion_from_planned(self):
		self.assertNotIn("completed", ACTION_TRANSITIONS["planned"])
		self.assertIn("completed", ACTION_TRANSITIONS["in_progress"])

	def test_completion_outcome_vocabulary_is_explicit(self):
		self.assertIn("APPLICATION_COMPLETED", OUTCOMES)
		self.assertNotIn("arbitrary free text", OUTCOMES)

	def test_reject_and_defer_reason_contract_rejects_blank_values(self):
		with self.assertRaises(StudentDecisionError) as error:
			_required("", "decision_reason")
		self.assertEqual(error.exception.code, "INVALID_INPUT")
