"""Focused HTTP adapter tests for lifecycle jump commands."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import student_lifecycle


class TestStudentLifecycleV2API(FrappeTestCase):
	def test_transition_endpoint_forwards_direct_target_and_all_evidence(self):
		payload = {
			"student": "STU-1",
			"target_stage": "Enrolled",
			"outcome_code": "qualified",
			"evidence_refs": [
				"outcome:CRM Student Outcome:OUT-1",
				"intent:CRM Intent:INT-1",
				"document:CRM Student Document:DOC-1",
			],
			"expected_revision": 3,
			"idempotency_key": "idem-1",
		}
		with patch("crm.api.student_lifecycle._request_transition", return_value={"status": "created"}) as command:
			self.assertEqual(student_lifecycle.request_transition(**payload), {"status": "created"})
		command.assert_called_once_with(**payload)

	def test_transition_adapter_discards_frappe_command_metadata(self):
		payload = {
			"student": "STU-1",
			"target_stage": "MQL",
			"expected_revision": 0,
			"idempotency_key": "idem-metadata",
		}
		with patch("crm.api.student_lifecycle._request_transition", return_value={"status": "created"}) as command:
			result = student_lifecycle.request_transition(cmd="crm.api.student_lifecycle.request_transition", **payload)
		self.assertEqual(result, {"status": "created"})
		command.assert_called_once_with(**payload)

	def test_reopen_adapter_forwards_revision_and_idempotency(self):
		with patch("crm.api.student_lifecycle._reopen", return_value={"status": "created"}) as command:
			result = student_lifecycle.reopen_student("STU-1", "Candidate returned", 4, "reopen-1", "corr-1")
		self.assertEqual(result, {"status": "created"})
		command.assert_called_once_with(
			student="STU-1", reason="Candidate returned", expected_revision=4, idempotency_key="reopen-1", correlation_id="corr-1"
		)
