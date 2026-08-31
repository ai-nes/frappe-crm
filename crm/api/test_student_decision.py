"""HTTP-contract tests for recommendation and Sales Action adapters."""

import hashlib
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import student_decision


class TestStudentDecisionAPI(FrappeTestCase):
	def test_generation_conflict_returns_current_revision_with_http_409(self):
		candidate = {"context_revision": 2, "disposition": "ACT", "action_type": "CALL"}
		payload_digest = hashlib.sha256(
			json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()
		).hexdigest()
		previous_revision = frappe.local.response.get("current_revision")
		try:
			with patch("crm.api.student_decision._require_v2_service"), patch(
				"crm.api.student_decision.frappe.db.get_value", return_value=None
			), patch(
				"crm.api.student_decision.frappe.db.sql",
				return_value=[frappe._dict(name="STU-1", student_context_revision=3)],
			):
				with self.assertRaises(frappe.ValidationError) as error:
					student_decision.upsert_crm_action(
						student="STU-1",
						expected_context_revision=2,
						generation_idempotency_key="generation-1",
						producer_identity="crm-agents:v2",
						payload_digest=payload_digest,
						rollout_epoch=0,
						candidate=candidate,
					)
			self.assertEqual(error.exception.http_status_code, 409)
			self.assertEqual(frappe.local.response["current_revision"], 3)
		finally:
			if previous_revision is None:
				frappe.local.response.pop("current_revision", None)
			else:
				frappe.local.response["current_revision"] = previous_revision

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
		with patch("crm.api.student_decision._transition_action", return_value={"status": "in_progress"}) as command:
			student_decision.transition_action(_internal_service=True, **payload)
		command.assert_called_once_with(**payload)
