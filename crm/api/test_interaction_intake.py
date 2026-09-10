from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api.interaction_intake import _interaction_response, _normalize_interaction_payload
from crm.fcrm.student_intake import StudentIntakeError


class TestInteractionIntakeContract(FrappeTestCase):
	def test_interaction_payload_requires_canonical_identity_and_labelled_turns(self):
		payload = _normalize_interaction_payload(
			{
				"source_namespace": "chatwoot",
				"source_record_id": "message-42",
				"idempotency_key": "idem-42",
				"student_id": "STU-1",
				"channel": "Facebook Messenger",
				"direction": "incoming",
				"turns": [{"speaker_role": "student", "content": "Need tuition details"}],
				"occurred_at": "2026-08-29 09:00:00",
				"agent_id": "agent-1",
				"conversation_id": "conversation-1",
			}
		)

		self.assertEqual(payload["source_namespace"], "chatwoot")
		self.assertEqual(payload["source_record_id"], "message-42")
		self.assertEqual(payload["student_id"], "STU-1")
		self.assertEqual(payload["channel"], "facebook")
		self.assertEqual(payload["direction"], "inbound")

	def test_unknown_channel_and_caller_authority_are_rejected(self):
		for payload in (
			{
				"source_namespace": "chatwoot",
				"source_record_id": "message-1",
				"idempotency_key": "idem-1",
				"student_id": "STU-1",
				"channel": "carrier-pigeon",
				"direction": "inbound",
				"turns": [{"speaker_role": "student", "content": "Hello"}],
				"occurred_at": "2026-08-29 09:00:00",
			},
			{
				"source_namespace": "chatwoot",
				"source_record_id": "message-2",
				"idempotency_key": "idem-2",
				"student_id": "STU-1",
				"channel": "facebook",
				"direction": "inbound",
				"turns": [{"speaker_role": "student", "content": "Hello"}],
				"occurred_at": "2026-08-29 09:00:00",
				"actor": "Administrator",
			},
		):
			with self.assertRaises(StudentIntakeError) as error:
				_normalize_interaction_payload(payload)
			self.assertEqual(error.exception.code, "INVALID_INPUT")

	def test_response_does_not_expose_internal_result_names(self):
		with patch(
			"crm.api.interaction_intake._submit_interaction",
			return_value={
				"outcome": "created",
				"interaction": "INT-1",
				"student": "STU-1",
				"contact": None,
				"receipt": "REC-1",
			},
		):
			from crm.api.interaction_intake import submit_interaction

			response = submit_interaction(
				{
					"source_namespace": "chatwoot",
					"source_record_id": "message-3",
					"idempotency_key": "idem-3",
					"student_id": "STU-1",
					"channel": "facebook",
					"direction": "inbound",
					"turns": [{"speaker_role": "student", "content": "Hello"}],
					"occurred_at": "2026-08-29 09:00:00",
				}
			)

		self.assertEqual(
			response,
			{
				"interaction_id": "INT-1",
				"student_id": "STU-1",
				"contact_id": None,
				"status": "created",
				"receipt_id": "REC-1",
			},
		)

	def test_response_exposes_analysis_run_for_service_worker(self):
		response = _interaction_response(
			{
				"outcome": "created",
				"interaction": "INT-1",
				"student": "STU-1",
				"analysis_run": "IAR-1",
			}
		)

		self.assertEqual(response["analysis_run"], "IAR-1")

	@patch("crm.fcrm.interaction_analysis.settle_interaction_analysis_result")
	def test_settlement_endpoint_forwards_semantic_contract_version(self, settle):
		from crm.api.interaction_intake import settle_interaction_analysis_result

		settle.return_value = {"result": "IRES-1"}
		signals = {"schema_revision": "nba-decision-signals-v1", "observations": []}
		response = settle_interaction_analysis_result(
			run_id="IAR-1",
			stage_generation=0,
			lease_token="lease",
			expected_source_revision=1,
			expected_source_digest="a" * 64,
			state="unknown",
			policy_revision="interaction-analysis-v2",
			model_revision="model",
			result_digest="b" * 64,
			contract_version="interaction-analysis-v2",
			decision_signals=signals,
		)

		self.assertEqual(response, {"result": "IRES-1"})
		self.assertEqual(settle.call_args.kwargs["contract_version"], "interaction-analysis-v2")
		self.assertEqual(settle.call_args.kwargs["decision_signals"], signals)
