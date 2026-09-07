# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Phase-00 producer-to-consumer boundary coverage for NBA Evaluation v1.

The fixture begins at the Frappe persistence boundary: it supplies records as
the real projection queries them, executes the real projection and the real
eligible-action filter, then passes that result through the envelope builder.
Consumer-kernel determinism is covered against this shared wire contract in
``crm-agents/tests/unit/test_nba_evaluator.py``.
"""

from datetime import datetime
import json
import pathlib
import unittest
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import student_decision_context
from crm.api.nba_evaluation import _shape_eligible_action_set, build_nba_evaluation_input
from crm.fcrm import nba_policy
from crm.fcrm.nba_canonical import canonical_digest
from crm.fcrm.nba_evaluation_input import input_digest
from crm.fcrm.test_nba_evaluation_contract import assert_input_shape


_NOW = datetime(2026, 9, 4, 2, 0)
_PRODUCER_FIXTURE = pathlib.Path(__file__).parents[1] / "fcrm" / "test_fixtures" / "nba-producer-phase00" / "input.json"


class TestNbaEvaluationProducer(FrappeTestCase):
	def test_production_shaped_projection_produces_stable_mapped_envelope(self):
		student = student_decision_context.frappe._dict(
			student_context_revision=42,
			lifecycle_stage="Qualified",
			enrollment_status=None,
			assessment_status="partial",
			assessment_revision=7,
			interest_level="high",
			fit_level="medium",
			primary_barrier="missing_document",
			latest_score=63,
			score_input_revision=42,
			applied_score_input_revision=42,
			applied_policy_revision=1,
			sla_evidence_state=None,
			sla_evidence_observed_at=None,
		)
		decision_policy = {
			"revision": "nba-decision-policy-r1",
			"score_threshold": 0.35,
			"confidence_floor": 0.45,
			"top_n_cap": 3,
			"recommendation_ttl_seconds": 604800,
			"component_weights": {"opportunity_fit": 0.45, "urgency": 0.25, "effectiveness_index": 0.30},
			"recent_contact_days": 2,
			"cooling_contact_days": 5,
			"contact_pressure_penalty": 0.15,
			"redundancy_penalty": 0.10,
			"diversity_group_penalty": 0.05,
			"deadline_horizon_days": 30,
		}
		decision = {
			"policy_revision": 1,
			"policy_digest": canonical_digest(decision_policy),
			"decision_policy": decision_policy,
		}

		def get_value(doctype, filters, fields, **kwargs):
			if doctype == "CRM Lead":
				return student
			if doctype == "CRM Intent":
				return student_decision_context.frappe._dict(
					intent_type="tuition", importance="high", confidence=0.9, polarity="positive", interaction="INT-1"
				)
			if doctype == "CRM Interaction":
				return student_decision_context.frappe._dict(
					interaction_type="Phone Call", outcome="follow up needed", interaction_datetime=_NOW
				)
			return None

		def get_all(doctype, **kwargs):
			filters = kwargs.get("filters") or {}
			if doctype == "CRM Admission Application":
				if "document_total" in (kwargs.get("fields") or []):
					return [{"name": "APP-0001", "status": "In Progress", "document_total": 2,
						"document_completed": 1, "deadline": "2026-09-08", "modified": "2026-09-04 01:00:00"}]
				return [{"deadline": "2026-09-08"}]
			if doctype == "CRM Student Academic Result":
				return []
			if doctype == "CRM Contact Consent Event":
				if filters.get("student"):
					return [{"name": "CONSENT-1", "event_type": "Granted", "scope": "email_phone_zalo",
						"occurred_at": "2026-09-01 09:00:00", "creation": "2026-09-01 09:00:00"}]
				return []
			if doctype == "CRM Action Item":
				return [{"action": "CALL", "action_type": "CONTACT", "state": "accepted",
					"execution_status": "not_started", "disposition": "ACT", "creation": "2026-09-03 09:00:00"}]
			if doctype == "CRM Action":
				return [{"code": "CALL", "display_name": "Call", "action_type": "CONTACT",
					"purpose": "Re-engage the student about tuition.", "default_channel": "CALL",
					"allowed_actors": ["Sale"], "requires_approval": 0, "requires_parent_authority": 0,
					"academic_constraint": None, "auto_execute": 0, "enabled": 1,
					"definition_revision": 3, "definition_digest": None,
					"effective_from": None, "effective_to": None}]
			return []

		with patch("crm.api.student_decision_context.frappe.db.get_value", side_effect=get_value), patch(
			"crm.api.student_decision_context.frappe.db.count", return_value=1
		), patch("crm.api.student_decision_context.frappe.db.get_single_value", return_value="Asia/Ho_Chi_Minh"), patch(
			"crm.api.student_decision_context.frappe.get_all", side_effect=get_all
		), patch("crm.api.student_decision_context.contacts_for_student", return_value=["CON-1"]), patch(
			"crm.api.student_decision_context.resolve_interaction_type",
			return_value={"channel": "phone", "purpose": "follow_up", "disposition": "follow_up"},
		), patch("crm.api.student_decision_context.get_active_policy", return_value={"policy_revision": 1}), patch(
			"crm.api.student_decision_context.frappe.utils.now_datetime", return_value=_NOW
		), patch("crm.api.student_decision_context.frappe.utils.getdate", return_value=_NOW.date()), patch(
			"crm.api.student_decision_context.allowed_generation_actions", return_value=["CALL"]
		), patch("crm.api.student_decision_context.parent_authority_is_valid", return_value=False), patch(
			"crm.api.student_decision_context.choose_next_task_policy", return_value=("CALL", "follow_up", True)
		), patch("crm.api.nba_evaluation.frappe.db.get_single_value", return_value="Asia/Ho_Chi_Minh"), patch(
			"crm.api.nba_evaluation.nba_policy.get_active_decision_policy", return_value=decision
		), patch("crm.fcrm.nba_policy._parent_authority_wire_channels", return_value=set()):
			first = build_nba_evaluation_input("ENR-2026-00001", now=_NOW, service_authorized=True)
			second = build_nba_evaluation_input("ENR-2026-00001", now=_NOW, service_authorized=True)

		assert_input_shape(first)
		print(json.dumps(first, sort_keys=True))
		self.assertEqual(first, json.loads(_PRODUCER_FIXTURE.read_text(encoding="utf-8")))
		self.assertEqual(input_digest(first), input_digest(second))
		self.assertEqual(first["context"]["application_state"]["missing"], ["required_documents"])
		self.assertEqual(first["context"]["application_state"]["source_revision"], "2026-09-04 01:00:00")
		self.assertEqual(first["context"]["engagement"]["state"], "cooling")
		self.assertEqual(first["context"]["work_in_flight"], ["CALL"])
		self.assertEqual(first["eligible_action_set"]["actions"][0]["action_code"], "CALL")
		self.assertEqual(first["eligible_action_set"]["actions"][0]["addresses_opportunities"], ["ENGAGE_OR_REENGAGE"])
		self.assertTrue(all(action["addresses_opportunities"] for action in first["eligible_action_set"]["actions"]))


class TestShapeEligibleActionSetTiming(unittest.TestCase):
	"""``CRM Action.allowed_time_slots`` -> ``normalized_timing_domain`` translation."""

	_DIGEST = "a" * 64

	def _eligible(self, allowed_time_slots):
		return {
			"revision": 1,
			"exclusions": [],
			"actions": [
				{
					"code": "CALL",
					"revision": 1,
					"digest": self._DIGEST,
					"category": "CONTACT",
					"default_channel": "CALL",
					"requires_parent_authority": False,
					"academic_constraint": {},
					"allowed_actors": ["Sale"],
					"purpose": "Re-engage the student.",
					"addresses_opportunities": ["ENGAGE_OR_REENGAGE"],
					"allowed_time_slots": allowed_time_slots,
				}
			],
		}

	def test_configured_slots_become_allowed_windows(self):
		shaped = _shape_eligible_action_set(self._eligible(["6-12", "18-24"]), timezone="Asia/Ho_Chi_Minh")
		domain = shaped["actions"][0]["normalized_timing_domain"]
		self.assertEqual(domain["timezone"], "Asia/Ho_Chi_Minh")
		self.assertEqual(
			domain["allowed_windows"],
			[
				{"code": "6-12", "from": "06:00", "to": "12:00"},
				{"code": "18-24", "from": "18:00", "to": "00:00"},
			],
		)

	def test_no_configured_slots_stays_unconstrained(self):
		shaped = _shape_eligible_action_set(self._eligible([]), timezone="Asia/Ho_Chi_Minh")
		self.assertEqual(shaped["actions"][0]["normalized_timing_domain"], {})

	def test_missing_slots_field_stays_unconstrained(self):
		shaped = _shape_eligible_action_set(self._eligible(None), timezone="Asia/Ho_Chi_Minh")
		self.assertEqual(shaped["actions"][0]["normalized_timing_domain"], {})
