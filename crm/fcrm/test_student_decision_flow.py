"""Decision/action command boundary tests without mutable fixtures."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_decision import (
	ACTION_TRANSITIONS,
	StudentDecisionError,
	_can_assign_global_executor,
	_canonical_decision_student,
	_required,
	_valid_executor,
)
from crm.services.action_outcome import OUTCOME_CODES


class TestStudentDecisionFlow(FrappeTestCase):
	def test_team_oversee_scope_can_assign_executor_across_student_teams(self):
		scope = {"capabilities": ["team.oversee"]}
		self.assertTrue(_can_assign_global_executor("lead.sale@example.test", scope))

	def test_decision_resolves_display_student_id_before_link_writes(self):
		doc = frappe._dict(doctype="CRM Recommendation", target_type="CRM Student", target_id="HS-2026-HCM-002284")
		with patch("crm.fcrm.student_decision.canonical_student", return_value="CRMC-2026-002284"):
			self.assertEqual(_canonical_decision_student(doc), "CRMC-2026-002284")

	def test_sales_action_state_machine_has_no_direct_completion_from_planned(self):
		self.assertNotIn("completed", ACTION_TRANSITIONS["planned"])
		self.assertIn("completed", ACTION_TRANSITIONS["in_progress"])

	def test_completion_outcome_vocabulary_is_explicit(self):
		self.assertIn("APPLICATION_COMPLETED", OUTCOME_CODES)
		self.assertNotIn("arbitrary free text", OUTCOME_CODES)

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
