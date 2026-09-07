"""Focused HTTP adapter tests for lifecycle jump commands."""

from unittest.mock import patch

import frappe
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

	def test_reopen_forwards_revision_and_idempotency(self):
		with patch("crm.api.student_lifecycle._reopen", return_value={"status": "created"}) as command:
			result = student_lifecycle.reopen("STU-1", "Candidate returned", 4, "reopen-1", "corr-1")
		self.assertEqual(result, {"status": "created"})
		command.assert_called_once_with(
			student="STU-1", reason="Candidate returned", expected_revision=4, idempotency_key="reopen-1", correlation_id="corr-1"
		)

	def test_get_lifecycle_stages_forwards_to_read_service(self):
		expected = {
			"stages": [{"stage": "Lead", "label": "Lead", "order": 0, "is_terminal": False}],
			"policy_version": "phase5-lifecycle-v1",
		}
		with patch("crm.api.student_lifecycle._get_lifecycle_stages", return_value=expected) as reader:
			result = student_lifecycle.get_lifecycle_stages()
		self.assertEqual(result, expected)
		reader.assert_called_once_with()

	def test_get_lifecycle_stages_returns_canonical_catalog(self):
		frappe.set_user("Administrator")

		self.assertEqual(
			student_lifecycle.get_lifecycle_stages(),
			{
				"stages": [
					{"stage": "Lead", "label": "Lead", "order": 0, "is_terminal": False},
					{"stage": "MQL", "label": "MQL", "order": 1, "is_terminal": False},
					{"stage": "Applicant", "label": "Applicant", "order": 2, "is_terminal": False},
					{"stage": "Enrolled", "label": "Enrolled", "order": 3, "is_terminal": False},
					{"stage": "Lost", "label": "Lost", "order": 4, "is_terminal": True},
				],
				"policy_version": "phase5-lifecycle-v1",
			},
		)
