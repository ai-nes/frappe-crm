"""HTTP-contract tests for recommendation and Sales Action adapters."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import student_decision


class TestStudentDecisionAPI(FrappeTestCase):
	def test_decision_adapter_forwards_idempotency_and_cas_revision(self):
		payload = {
			"name": "REC-1", "expected_revision": 2, "status": "rejected",
			"decision_reason": "Not relevant", "idempotency_key": "decision-1", "correlation_id": "corr-1",
		}
		with patch("crm.api.student_decision._decide_recommendation", return_value={"status": "rejected"}) as command:
			self.assertEqual(student_decision.decide_recommendation(**payload), {"status": "rejected"})
		command.assert_called_once_with(**payload)

	def test_action_adapter_removes_internal_service_bypass(self):
		payload = {"name": "ACT-1", "expected_revision": 1, "status": "in_progress", "idempotency_key": "action-1"}
		with patch("crm.api.student_decision._transition_sales_action", return_value={"status": "in_progress"}) as command:
			student_decision.transition_sales_action(_internal_service=True, **payload)
		command.assert_called_once_with(**payload)
