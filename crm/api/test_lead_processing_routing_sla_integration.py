"""Integration-level worker contracts for the Phase-2 lead-processing flow.

The disposable-site rehearsal supplies real doctypes and two database sessions.
These focused tests keep the worker state machine deterministic by passing an
explicit due time rather than sleeping.
"""

from contextlib import nullcontext
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm import student_sla


class TestSLAWorkerStateMachine(FrappeTestCase):
	def test_due_attempt_advances_warning_breach_and_escalation_once(self):
		attempt = frappe._dict(
			name="SLA-FLOW-1",
			status="open",
			revision=0,
			warning_at=10,
			breach_at=20,
			escalation_at=30,
			next_transition_at=10,
			recipient_strategy="owner_warning_lead_breach_director_daily_digest",
		)
		attempt.save = lambda ignore_permissions=True: None
		events, deliveries = [], []

		def event(_, event_type, **kwargs):
			events.append(event_type)
			return frappe._dict(name=f"EVENT-{event_type}")

		with patch.object(student_sla, "_lock_attempt", return_value=attempt), patch.object(
			student_sla, "_insert_event", side_effect=event
		), patch.object(student_sla, "_schedule_delivery", side_effect=lambda _, __, recipient: deliveries.append(recipient)), patch.object(
			student_sla, "service_context", return_value=nullcontext()
		), patch.object(student_sla.frappe.db, "commit"):
			student_sla._process_due_attempt(attempt.name, 10)
			student_sla._process_due_attempt(attempt.name, 20)
			student_sla._process_due_attempt(attempt.name, 30)

		self.assertEqual(events, ["warned", "breached", "escalated"])
		self.assertEqual(deliveries, ["owner", "lead_sales"])
		self.assertEqual(attempt.status, "escalated")
		self.assertIsNone(attempt.next_transition_at)
		self.assertEqual(attempt.revision, 3)

	def test_duplicate_due_worker_call_is_a_noop_after_terminal_transition(self):
		attempt = frappe._dict(name="SLA-FLOW-2", status="escalated")
		with patch.object(student_sla, "_lock_attempt", return_value=attempt), patch.object(
			student_sla, "_insert_event"
		) as event:
			student_sla._process_due_attempt(attempt.name, 99)
		event.assert_not_called()
