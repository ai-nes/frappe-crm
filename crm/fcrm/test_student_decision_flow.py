"""Decision/action command boundary tests without mutable fixtures."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_decision import (
	ACTION_TRANSITIONS,
	OUTCOMES,
	StudentDecisionError,
	_required,
	_valid_executor,
)


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

	def test_executor_uses_owner_team_when_student_team_projection_is_missing(self):
		staff_row = frappe._dict(user="executor@example.test", is_active=1)
		student_row = frappe._dict(
			owner_staff="Owner Staff", assigned_to="Owner Staff", owning_team=None, high_school=None
		)
		memberships = [frappe._dict(team="Sales Team", effective_from=None, effective_until=None)]

		with (
			patch.object(frappe.db, "get_value", side_effect=[staff_row, 1, student_row]),
			patch.object(frappe, "get_roles", return_value=["Lead Sale"]),
			patch(
				"crm.fcrm.student_decision.frappe.get_all",
				side_effect=[memberships, memberships],
			),
		):
			_valid_executor("STU-1", "Executor Staff")
