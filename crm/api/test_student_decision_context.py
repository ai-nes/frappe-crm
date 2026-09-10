# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for the additive score-evidence projection (`_score_projection`)
-- freshness must mirror the same (score_input_revision, policy_revision)
tuple ordering the CAS write layer
(`crm.api.scoring_write.append_score_if_current`) already uses."""

import hashlib
import json
import pathlib
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.nba_canonical import canonical_digest
from crm.api.student_decision_context import (
	_ENGAGEMENT_MAP,
	_canonical_label,
	_academic_projection,
	_contactability_projection,
	_consent_scope_channels,
	_days_to_deadline,
	_intent_observation_count,
	_interaction_recency,
	_recent_actions,
	_score_projection,
)


_CURRENT_GPA_FIXTURE = (
	pathlib.Path(__file__).parents[1] / "fcrm" / "test_fixtures" / "nba-producer-phase00" / "gpa-current.json"
)


class TestScoreProjection(FrappeTestCase):
	def _policy(self, policy_revision=1, policy_hash="deadbeef"):
		return {"policy_revision": policy_revision, "policy_hash": policy_hash}

	def test_unknown_when_never_scored(self):
		row = {
			"latest_score": None,
			"score_input_revision": 3,
			"applied_score_input_revision": 0,
			"applied_policy_revision": 0,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=self._policy()):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "unknown")
		self.assertEqual(result["current_revision"], 3)
		self.assertIsNone(result["required_revision"])

	def test_current_when_applied_matches_latest_facts_and_policy(self):
		row = {
			"latest_score": 55.0,
			"score_input_revision": 5,
			"applied_score_input_revision": 5,
			"applied_policy_revision": 1,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=self._policy(policy_revision=1)):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "current")

	def test_pending_when_a_newer_fact_revision_exists(self):
		row = {
			"latest_score": 40.0,
			"score_input_revision": 7,
			"applied_score_input_revision": 5,
			"applied_policy_revision": 1,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=self._policy(policy_revision=1)):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "pending")

	def test_pending_when_policy_revision_advanced_past_applied(self):
		row = {
			"latest_score": 40.0,
			"score_input_revision": 5,
			"applied_score_input_revision": 5,
			"applied_policy_revision": 1,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=self._policy(policy_revision=2)):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "pending")

	def test_no_active_policy_defaults_to_zero_revision(self):
		row = {
			"latest_score": 40.0,
			"score_input_revision": 0,
			"applied_score_input_revision": 0,
			"applied_policy_revision": 0,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=None):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "current")
		self.assertEqual(result["policy_revision"], 0)
		self.assertEqual(result["policy_hash"], "")


class TestDecisionEvidenceSignals(FrappeTestCase):
	"""Paired contract: the JSON shape these helpers feed into the projection is
	asserted on the crm-agents side in
	``tests/unit/test_student_task_v2_contracts.py``. Keep the two in lockstep."""

	def test_interaction_recency_is_none_without_a_last_interaction(self):
		self.assertIsNone(_interaction_recency({}))
		self.assertIsNone(_interaction_recency({"interaction_datetime": None}))

	def test_interaction_recency_is_whole_days_and_never_negative(self):
		import frappe

		past = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-6)
		self.assertEqual(_interaction_recency({"interaction_datetime": past}), 6)
		future = frappe.utils.add_to_date(frappe.utils.now_datetime(), days=3)
		self.assertEqual(_interaction_recency({"interaction_datetime": future}), 0)

	def test_intent_observation_count_is_zero_without_an_intent_type(self):
		self.assertEqual(_intent_observation_count("STU-1", None), 0)

	def test_intent_observation_count_reads_a_bounded_count(self):
		with patch(
			"crm.api.student_decision_context.frappe.db.count", return_value=4
		) as counter:
			self.assertEqual(_intent_observation_count("STU-1", "tuition"), 4)
		counter.assert_called_once_with("CRM Intent", {"student": "STU-1", "intent_type": "tuition"})

	def test_days_to_deadline_is_none_without_an_open_dated_application(self):
		with patch(
			"crm.api.student_decision_context.frappe.get_all", return_value=[]
		):
			self.assertIsNone(_days_to_deadline("STU-1"))

	def test_days_to_deadline_counts_whole_days_to_the_nearest_deadline(self):
		import frappe

		soon = frappe.utils.add_to_date(frappe.utils.getdate(), days=2)
		with patch(
			"crm.api.student_decision_context.frappe.get_all",
			return_value=[{"deadline": soon}],
		):
			self.assertEqual(_days_to_deadline("STU-1"), 2)

	def test_recent_actions_projects_canonical_semantic_fields_only(self):
		rows = [
			{
				"action": "CALL",
				"action_type": "CONTACT",
				"state": "completed",
				"execution_status": "done",
				"disposition": "ACT",
				"creation": "2026-08-28 09:00:00",
			},
			{
				"action_type": "DOCUMENT_REQUEST",
				"state": "pending",
				"execution_status": None,
				"disposition": None,
				"creation": None,
			},
		]
		with patch(
			"crm.api.student_decision_context.frappe.get_all", return_value=rows
		):
			projected = _recent_actions("STU-1")

		self.assertEqual(
			projected[0],
			{
				"action_type": "CALL",
				"action_category": "CONTACT",
				"state": "completed",
				"execution_status": "done",
				"disposition": "ACT",
				"at": "2026-08-28 09:00:00",
				"outcome_code": None,
			},
		)
		self.assertIsNone(projected[1]["at"])
		self.assertNotIn("objective", str(projected))

	def test_consent_scope_uses_explicit_channels_and_governed_legacy_scopes(self):
		self.assertEqual(_consent_scope_channels("email_phone_zalo"), {"CALL", "EMAIL", "MESSAGE"})
		self.assertEqual(_consent_scope_channels("student_profile_and_parent_follow_up"), set())
		self.assertEqual(_consent_scope_channels("admissions_processing"), set())
		self.assertEqual(_consent_scope_channels("unapproved-purpose"), set())

	def test_business_outcome_labels_do_not_become_engagement_evidence(self):
		self.assertEqual(_canonical_label("Resolved", _ENGAGEMENT_MAP), "unknown")
		self.assertEqual(_canonical_label("Converted", _ENGAGEMENT_MAP), "unknown")

	def test_recipient_binding_requires_exactly_one_contact(self):
		event = {
			"name": "CONSENT-1",
			"event_type": "Granted",
			"scope": "email",
			"occurred_at": "2026-08-20 09:00:00",
			"creation": "2026-08-20 09:00:00",
		}
		with patch("crm.api.student_decision_context.frappe.get_all", return_value=[event]):
			for contacts, expected in (([], False), (["CON-1"], True), (["CON-1", "CON-2"], False)):
				with patch("crm.api.student_decision_context.contacts_for_student", return_value=contacts):
					assert _contactability_projection("STU-1")["recipient_bound"] is expected

	def test_academic_projection_selects_one_latest_bounded_gpa(self):
		rows = [
			{"name": "GPA-11", "school_year": "2024-2025", "grade": "11", "gpa": 8.1, "modified": "2025-06-01", "idx": 1},
			{"name": "GPA-12", "school_year": "2025-2026", "grade": "12", "gpa": 8.8, "modified": "2026-06-01", "idx": 1},
		]
		with patch("crm.api.student_decision_context.frappe.get_all", return_value=rows):
			result = _academic_projection("STU-1")
		self.assertEqual(result["gpa"], 8.8)
		self.assertEqual(result["quality"], "current")
		self.assertEqual(result["evidence_ref"], "academic_result:GPA-12")

	def test_academic_projection_rejects_ambiguous_latest_rows(self):
		rows = [
			{"name": "GPA-A", "school_year": "2025-2026", "grade": "12", "gpa": 8.8, "modified": "2026-06-01", "idx": 1},
			{"name": "GPA-B", "school_year": "2025-2026", "grade": "12", "gpa": 8.6, "modified": "2026-06-02", "idx": 2},
		]
		with patch("crm.api.student_decision_context.frappe.get_all", return_value=rows):
			result = _academic_projection("STU-1")
		self.assertIsNone(result["gpa"])
		self.assertEqual(result["quality"], "conflicting")

	def test_academic_projection_prefers_student_rows_before_contact_fallback(self):
		raw = _CURRENT_GPA_FIXTURE.read_bytes()
		fixture = json.loads(raw)
		self.assertEqual(canonical_digest(fixture), "7df0d91b50db479d106e038f919e29d54b93d68c4c2cf4364de7bcfd2fb17132")
		self.assertEqual(hashlib.sha256(raw).hexdigest(), "bef5af2e221d388e0bbea9bf62294be9384306a74387ab5a69f0eba4c73ba674")
		student_row = {"name": "GPA-STU", "school_year": "2025-2026", "grade": "12", "gpa": 8.8, "modified": "2026-06-01 09:00:00", "idx": 1}
		contact_row = {"name": "GPA-CON", "school_year": "2025-2026", "grade": "12", "gpa": 9.4, "modified": "2026-06-02", "idx": 1}

		def get_all(_doctype, **kwargs):
			return [student_row] if kwargs["filters"]["parent"] == "STU-1" else [contact_row]

		with patch("crm.api.student_decision_context.frappe.get_all", side_effect=get_all), patch(
			"crm.api.student_decision_context.contacts_for_student", return_value=["CON-1"]
		) as contacts:
			result = _academic_projection("STU-1")

		self.assertEqual({key: result[key] for key in fixture["academic"]}, fixture["academic"])
		self.assertEqual(result["evidence_ref"], fixture["evidence_refs"][0])
		contacts.assert_not_called()

	def test_academic_projection_rejects_ambiguous_contact_fallback(self):
		with patch("crm.api.student_decision_context.frappe.get_all", return_value=[]), patch(
			"crm.api.student_decision_context.contacts_for_student", return_value=["CON-1", "CON-2"]
		):
			result = _academic_projection("STU-1")

		self.assertIsNone(result["gpa"])
		self.assertEqual(result["quality"], "unknown")
		self.assertEqual(result["source_revision"], "ambiguous_contact")

	def test_contactability_merges_student_and_legacy_contact_events(self):
		student_event = {
			"name": "CONSENT-1",
			"event_type": "Granted",
			"scope": "email",
			"occurred_at": "2026-08-20 09:00:00",
			"creation": "2026-08-20 09:00:00",
		}
		contact_event = {
			"name": "CONSENT-2",
			"event_type": "Granted",
			"scope": "phone_zalo",
			"occurred_at": "2026-08-21 09:00:00",
			"creation": "2026-08-21 09:00:00",
		}

		def fake_get_all(doctype, **kwargs):
			if kwargs.get("filters") == {"student": "STU-1"}:
				return [student_event]
			if kwargs.get("filters") == {"contact": ["in", ["CON-1"]]}:
				return [contact_event]
			return []

		with patch("crm.api.student_decision_context.contacts_for_student", return_value=["CON-1"]), patch(
			"crm.api.student_decision_context.frappe.get_all", side_effect=fake_get_all
		):
			result = _contactability_projection("STU-1")

		self.assertEqual(
			result,
			{"consent": True, "channels": ["CALL", "EMAIL", "MESSAGE"], "recipient_bound": True},
		)
