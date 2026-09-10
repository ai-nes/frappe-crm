import hashlib
import hmac
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.chatwoot_webhook import normalize_message_payload, receive, resolve_contact, verify_signature
from crm.fcrm.student_intake import StudentIntakeError


class TestChatwootWebhook(FrappeTestCase):
	def test_signature_matches_chatwoot_timestamp_and_raw_body_contract(self):
		body = b'{"event":"message_created","id":42}'
		timestamp = "1700000000"
		secret = "chatwoot-secret"
		signature = (
			"sha256="
			+ hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
		)
		with patch("crm.api.chatwoot_webhook.time.time", return_value=1700000000):
			self.assertTrue(verify_signature(body, timestamp, signature, secret))

	def test_stale_signature_is_rejected_before_payload_processing(self):
		with patch("crm.api.chatwoot_webhook.time.time", return_value=1700000000):
			with self.assertRaises(StudentIntakeError) as error:
				verify_signature(b"{}", "1699999000", "sha256=invalid", "secret")
		self.assertEqual(error.exception.code, "REPLAY_REJECTED")

	def test_normalize_message_payload_maps_chatwoot_fields(self):
		payload = {
			"id": 42,
			"content": "Em muốn hỏi học phí.",
			"created_at": 1700000000,
			"message_type": "incoming",
			"sender": {"id": 7, "type": "contact"},
			"conversation": {"id": 99, "channel": "Channel::FacebookPage"},
		}
		result = normalize_message_payload(payload, "CRMC-0001", "12")

		self.assertEqual(result["source_namespace"], "chatwoot")
		self.assertEqual(result["source_record_id"], "12:message:42")
		self.assertEqual(result["idempotency_key"], "12:message:42")
		self.assertEqual(result["contact_id"], "CRMC-0001")
		self.assertEqual(result["channel"], "facebook")
		self.assertEqual(result["direction"], "inbound")
		self.assertEqual(result["conversation_id"], "99")
		self.assertIsNone(result["agent_id"])
		self.assertEqual(result["evidence_kind"], "message")
		self.assertEqual(result["evidence_state"], "final")
		self.assertEqual(result["source_revision"], 1)
		self.assertEqual(
			result["turns"],
			[
				{
					"speaker_role": "student",
					"content": "Em muốn hỏi học phí.",
					"occurred_at": "2023-11-14 22:13:20",
				}
			],
		)
		self.assertNotIn("content", result)

	def test_normalize_message_payload_uses_agent_id_for_outgoing_message(self):
		result = normalize_message_payload(
			{
				"id": "message-1",
				"content": "I will check that for you.",
				"created_at": "2026-09-04T10:00:00.000Z",
				"message_type": "outgoing",
				"sender": {"id": 7, "type": "user"},
				"conversation": {"display_id": 8, "channel": "Channel::Api"},
			},
			"CRMC-0001",
			"12",
		)

		self.assertEqual(result["direction"], "outbound")
		self.assertEqual(result["channel"], "webchat")
		self.assertEqual(result["agent_id"], "7")
		self.assertEqual(result["conversation_id"], "8")
		self.assertEqual(result["occurred_at"], "2026-09-04 10:00:00")
		self.assertEqual(result["turns"][0]["speaker_role"], "advisor")
		self.assertEqual(result["turns"][0]["content"], "I will check that for you.")
		self.assertEqual(result["turns"][0]["occurred_at"], result["occurred_at"])
		self.assertNotIn("content", result)

	def test_resolve_contact_falls_back_to_unique_email_and_binds_chatwoot_id(self):
		with (
			patch("crm.api.chatwoot_webhook._has_contact_mapping_field", return_value=False),
			patch("crm.api.chatwoot_webhook._contact_names_by_email", return_value={"CRMC-0001"}),
			patch("crm.api.chatwoot_webhook._bind_chatwoot_contact") as bind,
		):
			name = resolve_contact({"id": 42, "email": "student@example.com"})

		self.assertEqual(name, "CRMC-0001")
		bind.assert_called_once_with("CRMC-0001", "42")

	def test_resolve_contact_rejects_ambiguous_identity(self):
		with (
			patch("crm.api.chatwoot_webhook._has_contact_mapping_field", return_value=False),
			patch(
				"crm.api.chatwoot_webhook._contact_names_by_email", return_value={"CRMC-0001", "CRMC-0002"}
			),
		):
			with self.assertRaises(StudentIntakeError) as error:
				resolve_contact({"id": 42, "email": "shared@example.com"})

		self.assertEqual(error.exception.code, "AMBIGUOUS_TARGET")

	def test_receive_ignores_non_message_events_without_mutating_crm(self):
		payload = {"event": "conversation_updated", "account": {"id": 12}}
		with (
			patch("crm.api.chatwoot_webhook._raw_body", return_value=b"{}"),
			patch("crm.api.chatwoot_webhook.verify_signature"),
			patch("crm.api.chatwoot_webhook._json_body", return_value=payload),
			patch("crm.api.chatwoot_webhook._assert_account", return_value="12"),
			patch("crm.api.chatwoot_webhook.ingest_external_interaction") as ingest,
		):
			result = receive()

		self.assertEqual(result["status"], "ignored")
		ingest.assert_not_called()

	def test_receive_ignores_chatwoot_activity_messages(self):
		payload = {"event": "message_created", "message_type": 2, "account": {"id": 12}}
		with (
			patch("crm.api.chatwoot_webhook._raw_body", return_value=b"{}"),
			patch("crm.api.chatwoot_webhook.verify_signature"),
			patch("crm.api.chatwoot_webhook._json_body", return_value=payload),
			patch("crm.api.chatwoot_webhook._assert_account", return_value="12"),
			patch("crm.api.chatwoot_webhook.ingest_external_interaction") as ingest,
		):
			result = receive()

		self.assertEqual(result["status"], "ignored")
		ingest.assert_not_called()

	def test_receive_delegates_message_to_canonical_interaction_command(self):
		payload = {
			"event": "message_created",
			"id": 42,
			"account": {"id": 12},
			"content": "Hello",
			"message_type": "incoming",
			"conversation": {
				"id": 99,
				"meta": {"sender": {"id": 7, "phone_number": "+84984251625"}},
			},
		}
		with (
			patch("crm.api.chatwoot_webhook._raw_body", return_value=b"{}"),
			patch("crm.api.chatwoot_webhook.verify_signature"),
			patch("crm.api.chatwoot_webhook._json_body", return_value=payload),
			patch("crm.api.chatwoot_webhook._assert_account", return_value="12"),
			patch("crm.api.chatwoot_webhook.resolve_contact", return_value="CRMC-0001") as resolve_contact,
			patch("crm.api.chatwoot_webhook._signed_context", return_value={"scope_all": True}),
			patch(
				"crm.api.chatwoot_webhook.ingest_external_interaction",
				return_value={
					"outcome": "created",
					"interaction": "INTX-1",
					"contact": "CRMC-0001",
					"receipt": "REC-1",
				},
			) as ingest,
		):
			result = receive()

		self.assertEqual(result.status_code, 200)
		self.assertEqual(json.loads(result.get_data(as_text=True)), {"status": "ok"})
		resolve_contact.assert_called_once_with(
			{"id": 7, "phone_number": "+84984251625"}
		)
		ingest.assert_called_once()
		canonical = ingest.call_args.args[0]
		self.assertEqual(canonical["source_record_id"], "12:message:42")
		self.assertEqual(canonical["contact_id"], "CRMC-0001")
		self.assertEqual(canonical["direction"], "inbound")
		self.assertEqual(canonical["turns"][0]["speaker_role"], "student")
		self.assertEqual(canonical["turns"][0]["content"], "Hello")
		self.assertNotIn("content", canonical)
		self.assertEqual(ingest.call_args.kwargs, {"signed_context": {"scope_all": True}})

	def test_receive_returns_validation_error_when_sender_phone_is_missing(self):
		payload = {
			"event": "message_created",
			"id": 42,
			"conversation": {"meta": {"sender": {"id": 7, "phone_number": None}}},
		}
		with (
			patch("crm.api.chatwoot_webhook._raw_body", return_value=b"{}"),
			patch("crm.api.chatwoot_webhook.verify_signature"),
			patch("crm.api.chatwoot_webhook._json_body", return_value=payload),
			patch("crm.api.chatwoot_webhook._assert_account", return_value="12"),
			patch("crm.api.chatwoot_webhook.ingest_external_interaction") as ingest,
		):
			result = receive()

		self.assertEqual(result.status_code, 422)
		body = json.loads(result.get_data(as_text=True))
		self.assertEqual(body["error"], "validation_error")
		self.assertEqual(body["detail"], "Missing phone_number in conversation.meta.sender")
		self.assertIsNone(body["session_id"])
		self.assertTrue(body["request_id"])
		ingest.assert_not_called()
