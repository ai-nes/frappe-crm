from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests
from frappe.tests.utils import FrappeTestCase

from crm.api.copilot_delegation import (
	_is_copilot_authorized,
	_relay_upstream,
	_require_copilot_user,
	_utc_epoch_seconds,
	run_student_analysis,
	stream_chat,
)


class _FakeUpstream:
	def __init__(self, lines, error=None):
		self.lines = lines
		self.error = error
		self.calls = []
		self.closed = False

	def iter_lines(self, **kwargs):
		self.calls.append(kwargs)
		if self.error:
			raise self.error
		yield from self.lines

	def close(self):
		self.closed = True


class TestCopilotDelegationRelay(FrappeTestCase):
	def test_stream_response_is_a_finite_sse_body(self):
		upstream = _FakeUpstream(['data: {"type":"finish"}'])
		with (
			patch("crm.api.copilot_delegation._require_copilot_user"),
			patch("crm.api.copilot_delegation._request_payload", return_value={"messages": []}),
			patch("crm.api.copilot_delegation._agent_config", return_value=("http://agent", "key")),
			patch("crm.api.copilot_delegation.mint_delegated_credential", return_value={"bearer": "token", "proof": "proof"}),
			patch("crm.api.copilot_delegation.requests.post", return_value=MagicMock(status_code=200, iter_lines=upstream.iter_lines, close=upstream.close)),
		):
			response = stream_chat()

		self.assertIn('"type":"finish"', response.get_data(as_text=True))
		self.assertNotIn("Connection", response.headers)
		self.assertEqual(response.content_type, "text/event-stream")

	def test_delegation_timestamp_is_always_utc(self):
		instant = datetime(2026, 8, 23, 16, 55, 30, tzinfo=timezone.utc)
		with patch("crm.api.copilot_delegation.datetime") as mocked_datetime:
			mocked_datetime.now.return_value = instant
			self.assertEqual(_utc_epoch_seconds(), 1787504130)
			mocked_datetime.now.assert_called_once_with(timezone.utc)

	def test_system_manager_is_denied_even_with_a_business_profile(self):
		self.assertFalse(_is_copilot_authorized({"System Manager"}))
		self.assertFalse(_is_copilot_authorized({"System Manager", "Sale"}))
		self.assertTrue(_is_copilot_authorized({"Sale"}))
		self.assertFalse(_is_copilot_authorized({"Counseller"}))
		self.assertFalse(_is_copilot_authorized({"Unrelated Role"}))

	def test_student_nba_operator_profiles_are_authorized(self):
		for role in ("CTV Sale", "Sale", "Lead Sale", "Administrator", "Admissions Director"):
			with self.subTest(role=role):
				self.assertTrue(_is_copilot_authorized({role}))

	def test_copilot_uses_normalized_roles_for_the_ceo_profile(self):
		with (
			patch(
				"crm.api.copilot_delegation.frappe.session",
				SimpleNamespace(user="ceo@example.com", sid="session-id"),
			),
			patch("crm.api.session.get_session_role_flags"),
			patch("crm.api.session._get_policy_roles", return_value=["Administrator"]),
			patch("crm.api.copilot_delegation._is_copilot_authorized", return_value=True) as authorized,
		):
			_require_copilot_user()

		authorized.assert_called_once_with(["Administrator"])

	def test_student_analysis_normalizes_legacy_lead_id(self):
		with (
			patch(
				"crm.api.copilot_delegation._validate_analysis_target",
				return_value="ENR-2026-00003",
			),
			patch("crm.api.copilot_delegation._validate_analysis_force_reason", return_value=None),
			patch("crm.api.copilot_delegation._validate_analysis_idempotency_key", return_value="analysis-test-key"),
			patch("crm.fcrm.student_reference.canonical_student", return_value="CRMC-2026-00003"),
			patch("crm.api.copilot_delegation._run_analysis_agent", return_value="response") as run,
		):
			self.assertEqual(run_student_analysis("ENR-2026-00003"), "response")

		run.assert_called_once_with(
			"/api/v1/analysis-runs/student/run",
			{"student_id": "CRMC-2026-00003"},
			"analysis-test-key",
		)

	def test_relay_flushes_small_chunks_and_preserves_finish(self):
		upstream = _FakeUpstream([
			'data: {"type":"text-delta","delta":"Hi"}',
			'data: {"type":"finish"}',
		])

		body = b"".join(_relay_upstream(upstream)).decode()

		self.assertEqual(upstream.calls, [{"chunk_size": 1, "decode_unicode": True}])
		self.assertIn('data: {"type":"finish"}', body)
		self.assertNotIn("upstream_stream_incomplete", body)
		self.assertTrue(upstream.closed)

	def test_relay_turns_unexpected_eof_into_sse_error(self):
		upstream = _FakeUpstream(['data: {"type":"start"}'])

		body = b"".join(_relay_upstream(upstream)).decode()

		self.assertIn('"error":"upstream_stream_incomplete"', body)
		self.assertTrue(upstream.closed)

	def test_relay_turns_upstream_exception_into_sse_error(self):
		upstream = _FakeUpstream([], error=requests.RequestException("closed"))

		body = b"".join(_relay_upstream(upstream)).decode()

		self.assertIn('"error":"upstream_stream_unavailable"', body)
		self.assertTrue(upstream.closed)

	def test_relay_closes_upstream_when_browser_generator_is_cancelled(self):
		upstream = _FakeUpstream([
			'data: {"type":"text-delta","delta":"partial"}',
		])
		relay = _relay_upstream(upstream)

		next(relay)
		relay.close()

		self.assertTrue(upstream.closed)

	def test_relay_drops_contradictory_terminal_events(self):
		upstream = _FakeUpstream([
			'data: {"type":"error","error":"failed"}',
			'data: {"type":"finish"}',
		])

		body = b"".join(_relay_upstream(upstream)).decode()

		self.assertIn('"type":"error"', body)
		self.assertNotIn('"type":"finish"', body)
		self.assertTrue(upstream.closed)
