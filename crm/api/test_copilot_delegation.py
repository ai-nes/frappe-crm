from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import requests
from frappe.tests.utils import FrappeTestCase

from crm.api.copilot_delegation import (
	_is_copilot_authorized,
	_relay_upstream,
	_utc_epoch_seconds,
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

	def test_system_manager_is_authorized_without_a_business_profile(self):
		self.assertTrue(_is_copilot_authorized({"is_system_manager": True, "crm_profile": None}))
		self.assertTrue(_is_copilot_authorized({"is_system_manager": False, "crm_profile": "sales"}))
		self.assertFalse(_is_copilot_authorized({"is_system_manager": False, "crm_profile": None}))

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
