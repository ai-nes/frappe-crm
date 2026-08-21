from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.agent_events import record_agent_event


class TestCRMAgentEvent(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		for name in frappe.get_all("CRM Agent Event", filters={"aggregate_name": "_Test Event Aggregate"}, pluck="name"):
			frappe.delete_doc("CRM Agent Event", name, force=True)

	def test_records_outbox_event_before_scheduling_delivery(self):
		doc = SimpleNamespace(
			doctype="CRM Recommendation",
			name="_Test Event Aggregate",
			modified="2026-08-21 22:00:00.000000",
		)
		with patch("frappe.enqueue") as enqueue:
			event_name = record_agent_event("recommendation.decided.v1", doc)

		event = frappe.get_doc("CRM Agent Event", event_name)
		self.assertEqual(event.event_type, "recommendation.decided.v1")
		self.assertEqual(event.aggregate_name, doc.name)
		self.assertEqual(event.source_revision, doc.modified)
		self.assertEqual(event.status, "pending")
		enqueue.assert_called_once_with(
			"crm.api.agent_events.deliver_agent_event",
			queue="short",
			enqueue_after_commit=True,
			event_name=event_name,
		)
