"""Contract-version checks reject incompatible payloads before delivery."""

import json
from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api.agent_events import _check_agent_contract_version, _event_body


class TestAgentEventContractVersion(FrappeTestCase):
	def _score_event(self, **overrides):
		identity = {
			"rule_version": "RULES-2026-09",
			"rule_version_digest": "a" * 64,
			"ruleset_digest": "a" * 64,
		}
		values = {
			"event_id": "E-SCORE-1",
			"event_type": "student.score_input_changed.v1",
			"aggregate_doctype": "CRM Student",
			"aggregate_name": "STU-1",
			"source_revision": "7",
			"source_revision_bigint": 7,
			"contract_version": 1,
			"occurred_at": "2026-09-10 00:00:00",
			"payload": json.dumps(identity, sort_keys=True, separators=(",", ":")),
			**identity,
		}
		values.update(overrides)
		return SimpleNamespace(**values)

	def test_score_input_body_contains_only_signed_identity_fields(self):
		body = json.loads(_event_body(self._score_event()))

		self.assertEqual(
			set(body),
			{
				"event_id",
				"event_type",
				"aggregate_doctype",
				"aggregate_name",
				"source_revision",
				"contract_version",
				"occurred_at",
				"student_id",
				"score_input_revision",
				"rule_version",
				"rule_version_digest",
				"ruleset_digest",
			},
		)
		self.assertEqual(body["student_id"], "STU-1")
		self.assertEqual(body["score_input_revision"], 7)
		self.assertNotIn("payload", body)

	def test_score_input_body_rejects_mismatched_identity(self):
		with self.assertRaises(ValueError):
			_event_body(self._score_event(ruleset_digest="b" * 64))

	def test_score_input_body_rejects_non_identity_payload(self):
		with self.assertRaises(ValueError):
			_event_body(
				self._score_event(
					payload=json.dumps(
						{
							"rule_version": "RULES-2026-09",
							"rule_version_digest": "a" * 64,
							"ruleset_digest": "a" * 64,
							"student_name": "PII sentinel",
						}
					)
				)
			)

	def test_known_matching_version_is_accepted(self):
		event = SimpleNamespace(event_type="student.score_input_changed.v1", contract_version=1, name="E-1")

		with patch("crm.api.agent_events._fetch_agent_contract_manifest", return_value=None):
			self.assertTrue(_check_agent_contract_version(event))

	def test_known_mismatch_is_logged_without_raising(self):
		event = SimpleNamespace(event_type="student.score_input_changed.v1", contract_version=2, name="E-2")
		with patch("frappe.logger") as logger_factory, patch(
			"crm.api.agent_events._fetch_agent_contract_manifest", return_value=None
		):
			self.assertFalse(_check_agent_contract_version(event))

		logger_factory.return_value.warning.assert_called_once()

	def test_producer_manifest_is_preferred_when_available(self):
		event = SimpleNamespace(event_type="student.score_input_changed.v1", contract_version=2, name="E-3")
		manifest = {
			"events": [
				{"event_type": "student.score_input_changed.v1", "contract_version": 2},
			],
		}
		with patch("crm.api.agent_events._fetch_agent_contract_manifest", return_value=manifest):
			self.assertTrue(_check_agent_contract_version(event))

	def test_event_missing_from_producer_manifest_is_rejected(self):
		event = SimpleNamespace(event_type="student.score_input_changed.v1", contract_version=1, name="E-4")
		with patch("frappe.logger") as logger_factory:
			with patch("crm.api.agent_events._fetch_agent_contract_manifest", return_value={"events": []}):
				self.assertFalse(_check_agent_contract_version(event))

		logger_factory.return_value.warning.assert_called_once()
