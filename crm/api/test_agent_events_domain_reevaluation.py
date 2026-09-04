"""Domain-event NBA re-evaluation admission gating and delegation."""

from contextlib import contextmanager
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.agent_events import (
	dispatch_intent_domain_reevaluation,
	dispatch_interaction_domain_reevaluation,
	record_domain_reevaluation_trigger,
)


@contextmanager
def _flag(value):
	previous = frappe.conf.get("crm_nba_domain_reevaluation_enabled")
	frappe.conf["crm_nba_domain_reevaluation_enabled"] = value
	try:
		yield
	finally:
		if previous is None:
			frappe.conf.pop("crm_nba_domain_reevaluation_enabled", None)
		else:
			frappe.conf["crm_nba_domain_reevaluation_enabled"] = previous


class TestDomainReevaluationTrigger(FrappeTestCase):
	def test_disabled_flag_is_a_safe_no_op(self):
		with _flag(0):
			result = record_domain_reevaluation_trigger("STU-1", trigger="student_state_changed")

		self.assertEqual(result, {"enabled": False, "created": None, "coalesced": False, "matched_waits": 0})

	def test_blank_student_or_trigger_is_a_safe_no_op(self):
		with _flag(1):
			self.assertIsNone(record_domain_reevaluation_trigger("   ", trigger="new_interaction")["created"])
			self.assertIsNone(record_domain_reevaluation_trigger("STU-1", trigger="  ")["created"])

	def test_enabled_delegates_to_the_coalescing_primitive(self):
		with (
			_flag(1),
			patch("crm.fcrm.nba_evaluations.request_domain_reevaluation") as delegate,
		):
			delegate.return_value = {
				"enabled": True,
				"created": "NBAEVAL-1",
				"coalesced": False,
				"matched_waits": 0,
			}
			result = record_domain_reevaluation_trigger(" STU-1 ", trigger=" new_interaction ")

		delegate.assert_called_once_with("STU-1", trigger_reason="new_interaction")
		self.assertEqual(result["created"], "NBAEVAL-1")


class TestDomainReevaluationDocEventHooks(FrappeTestCase):
	"""``hooks.py`` wires these onto ``CRM Interaction``/``CRM Intent`` -- the
	live callers that make the coalescing primitive reachable outside its own
	tests. Both must stay safe-by-default and never raise into the doc write
	they hang off."""

	def test_hooks_registers_both_dispatchers_on_their_doctype_events(self):
		from crm.hooks import doc_events

		for doctype, event in (("CRM Interaction", "after_insert"), ("CRM Interaction", "on_update")):
			self.assertIn(
				"crm.api.agent_events.dispatch_interaction_domain_reevaluation", doc_events[doctype][event]
			)
		for doctype, event in (("CRM Intent", "after_insert"), ("CRM Intent", "on_update")):
			self.assertIn(
				"crm.api.agent_events.dispatch_intent_domain_reevaluation", doc_events[doctype][event]
			)

	def test_interaction_dispatcher_is_a_no_op_without_a_student(self):
		with patch("crm.api.agent_events.record_domain_reevaluation_trigger") as delegate:
			dispatch_interaction_domain_reevaluation(frappe._dict(student=None, name="INT-1"))
		delegate.assert_not_called()

	def test_interaction_dispatcher_delegates_with_the_student_and_interaction_trigger(self):
		with (
			_flag(1),
			patch("crm.api.agent_events.record_domain_reevaluation_trigger") as delegate,
		):
			dispatch_interaction_domain_reevaluation(frappe._dict(student="STU-1", name="INT-1"))
		delegate.assert_called_once_with("STU-1", trigger="interaction")

	def test_interaction_dispatcher_swallows_a_delegate_failure(self):
		"""A domain re-evaluation dispatch failure must never abort the write
		it hangs off -- it is best-effort enrichment, not part of the Interaction
		transaction's correctness."""
		with patch(
			"crm.api.agent_events.record_domain_reevaluation_trigger", side_effect=RuntimeError("boom")
		):
			dispatch_interaction_domain_reevaluation(frappe._dict(student="STU-1", name="INT-1"))  # no raise

	def test_intent_dispatcher_delegates_with_the_student_and_intent_trigger(self):
		with (
			_flag(1),
			patch("crm.api.agent_events.record_domain_reevaluation_trigger") as delegate,
		):
			dispatch_intent_domain_reevaluation(frappe._dict(student="STU-1", name="INTENT-1"))
		delegate.assert_called_once_with("STU-1", trigger="intent")

	def test_intent_dispatcher_swallows_a_delegate_failure(self):
		with patch(
			"crm.api.agent_events.record_domain_reevaluation_trigger", side_effect=RuntimeError("boom")
		):
			dispatch_intent_domain_reevaluation(frappe._dict(student="STU-1", name="INTENT-1"))  # no raise
