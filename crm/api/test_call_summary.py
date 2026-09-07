"""Contract tests for the Frappe-to-crm-agents call summary gateway."""

from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.call_summary import summarize_call


class TestCallSummaryAPI(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._previous_url = frappe.conf.get("crm_agents_url")
		self._previous_key = frappe.conf.get("crm_agents_api_key")
		frappe.conf.crm_agents_url = "http://crm-agents.test"
		frappe.conf.crm_agents_api_key = "test-key"

	def tearDown(self):
		if self._previous_url is None:
			frappe.conf.pop("crm_agents_url", None)
		else:
			frappe.conf.crm_agents_url = self._previous_url
		if self._previous_key is None:
			frappe.conf.pop("crm_agents_api_key", None)
		else:
			frappe.conf.crm_agents_api_key = self._previous_key

	def test_summary_is_forwarded_to_ai_gateway(self):
		response = Mock()
		response.json.return_value = {
			"summary": "Đã trao đổi nhu cầu tuyển sinh.",
			"key_points": ["Quan tâm ngành học."],
			"action_items": [],
			"sentiment": "neutral",
			"next_step": "Gọi lại.",
		}
		with (
			patch("crm.api.call_summary.frappe.db.exists", return_value=True),
			patch("crm.api.call_summary.frappe.has_permission", return_value=True),
			patch("crm.api.call_summary.requests.post", return_value=response) as post,
		):
			result = summarize_call(
				"1788077950.625384",
				"SPEAKER_00: Em quan tâm ngành học.",
				'[{"speaker": "SPEAKER_00", "text": "Em quan tâm ngành học."}]',
			)

		post.assert_called_once()
		self.assertEqual(post.call_args.args[0], "http://crm-agents.test/api/v1/call-summary")
		self.assertEqual(post.call_args.kwargs["headers"]["X-API-Key"], "test-key")
		self.assertEqual(result["sentiment"], "neutral")
		self.assertEqual(result["summary"], "Đã trao đổi nhu cầu tuyển sinh.")
