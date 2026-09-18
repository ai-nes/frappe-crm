"""HTTP-contract tests for recommendation and Sales Action adapters."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import student_decision
from crm.fcrm.student_decision import _validate_decision_executor


class TestStudentDecisionAPI(FrappeTestCase):
	def test_lead_sale_can_validate_an_executor_outside_student_team(self):
		with (
			patch("crm.fcrm.student_decision._staff_for_user", return_value="LEAD-STAFF"),
			patch("crm.fcrm.student_decision._valid_executor") as valid_executor,
		):
			_validate_decision_executor(
				"lead-sale@example.test",
				{"capabilities": ["team.oversee"]},
				"STU-1",
				"SALE-STAFF",
			)

		valid_executor.assert_called_once_with("STU-1", "SALE-STAFF", allow_global=True)

	def test_sale_cannot_validate_an_executor_outside_student_team(self):
		with patch("crm.fcrm.student_decision._staff_for_user", return_value="SALE-STAFF"):
			with self.assertRaises(frappe.ValidationError) as error:
				_validate_decision_executor(
					"sale@example.test",
					{"capabilities": ["student.execute", "action.execute"]},
					"STU-1",
					"OTHER-STAFF",
				)

		self.assertIn("FORBIDDEN", str(error.exception))

	def test_decision_adapter_forwards_idempotency_and_cas_revision(self):
		payload = {
			"name": "REC-1", "expected_revision": 2, "status": "rejected",
			"decision_reason": "Not relevant", "idempotency_key": "decision-1", "correlation_id": "corr-1",
		}
		with patch("crm.api.student_decision._decide_recommendation", return_value={"status": "rejected"}) as command:
			result = student_decision.decide_recommendation(
				cmd="crm.api.student_decision.decide_recommendation", **payload
			)
		self.assertEqual(result["status"], "rejected")
		command.assert_called_once_with(**payload)

	def test_action_adapter_removes_internal_service_bypass(self):
		payload = {"name": "ACT-1", "expected_revision": 1, "status": "in_progress", "idempotency_key": "action-1"}
		with patch("crm.api.student_decision._transition_action", return_value={"status": "in_progress"}) as command:
			student_decision.transition_action(_internal_service=True, **payload)
		command.assert_called_once_with(**payload)

	def test_create_action_strips_routed_rpc_command(self):
		"""Every real HTTP call to a Frappe RPC method injects ``cmd`` into
		**kwargs; create_action must strip it like the other adapters do,
		instead of forwarding it into _create_manual_action."""
		payload = {"student": "STU-1", "action_type": "CALL", "objective": "Follow up", "idempotency_key": "manual-1"}
		with patch("crm.api.student_decision._create_manual_action", return_value={"status": "accepted"}) as command:
			result = student_decision.create_action(cmd="crm.api.student_decision.create_action", **payload)
		self.assertEqual(result["status"], "accepted")
		command.assert_called_once_with(**payload)
