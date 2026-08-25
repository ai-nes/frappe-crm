"""Focused contract checks for the reduced lead-processing flow."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import agent_events


class TestLeadProcessingFlowV2(FrappeTestCase):
	@patch("crm.api.agent_events.record_sla_digest")
	def test_daily_digest_uses_previous_day_and_is_repeatable(self, record_digest):
		class DB:
			def count(self, doctype, filters):
				self.filters = filters
				return 2

			def get_value(self, doctype, filters, fieldname):
				if doctype == "User" and fieldname == "enabled":
					return 1
				return None

			db = self

		class FrappeStub:
			db = DB()

			def get_all(self, doctype, filters, pluck):
				return ["director@example.com"]

		frappe_stub = FrappeStub()
		with patch.object(agent_events, "frappe", frappe_stub), patch.object(
			agent_events, "now_datetime", return_value="2026-08-26 09:00:00"
		):
			result = agent_events.send_daily_sla_director_digests()

		self.assertEqual(result, {"created": 1, "skipped": 0})
		self.assertEqual(frappe_stub.db.filters["status"], "escalated")
		self.assertIn("2026-08-25", frappe_stub.db.filters["escalation_at"][1][0])
		record_digest.assert_called_once_with(
			recipient_user="director@example.com", digest_date="2026-08-25", unresolved_count=2
		)
