import unittest
from unittest.mock import patch

from crm.fcrm import intelligence_runs


class TestIntelligenceRunSecurity(unittest.TestCase):
	def test_visibility_recheck_requires_every_resolvable_source(self):
		with patch("crm.fcrm.intelligence_runs.frappe.db.exists", return_value=True), patch(
			"crm.fcrm.intelligence_runs.frappe.has_permission", side_effect=[True, False]
		):
			self.assertFalse(intelligence_runs._claim_visible(["school:SCH-1", "snapshot:SNAP-1"]))

	def test_visibility_recheck_fails_closed_for_opaque_provenance(self):
		self.assertFalse(intelligence_runs._claim_visible(["legacy-hash"]))

	def test_visible_claims_suppresses_whole_claim(self):
		claims = [
			{"kind": "fact", "text": "visible", "provenance_ids": ["student:STU-1"], "visibility": "shareable"},
			{"kind": "inference", "text": "hidden", "provenance_ids": ["unknown:X"], "visibility": "shareable"},
		]
		with patch("crm.fcrm.intelligence_runs.frappe.db.exists", return_value=True), patch(
			"crm.fcrm.intelligence_runs.frappe.has_permission", return_value=True
		):
			self.assertEqual([claim["text"] for claim in intelligence_runs.visible_claims(claims)], ["visible"])

	def test_school_source_revision_uses_monotonic_cursor_not_digest(self):
		with patch("crm.fcrm.intelligence_runs.frappe.db.get_value", return_value=17), patch(
			"crm.fcrm.intelligence_runs.get_school_intelligence", return_value={"school": "SCH-1", "x": 1}
		):
			revision, _digest = intelligence_runs._source("school", "SCH-1")
		self.assertEqual(revision, "17")

	def test_student_stage_evidence_is_minimized_and_uses_resolvable_provenance(self):
		projection = {
			"student_id": "STU-1", "returned_revision": 9, "snapshot_hash": "a" * 64,
			"policy_version": "policy", "eligibility": {"student": True},
			"lifecycle": {"stage": "Qualified"}, "intent": {"type": "fees"},
			"score": {"freshness": "current"}, "interaction": {"outcome": "Interested"},
			"sla_evidence": {"state": "known"}, "allowed_action_types": ["CALL"],
			"student_name": "must-not-cross-boundary", "phone": "must-not-cross-boundary",
		}
		row = {"lifecycle_stage": "Qualified", "interest_level": "High", "fit_level": "High"}
		with patch("crm.api.student_decision_context._projection", return_value=projection), patch(
			"crm.fcrm.intelligence_runs.frappe.db.get_value", return_value=row
		):
			evidence = intelligence_runs._student_stage_evidence("STU-1", "9")
		self.assertEqual(evidence["decision_context"]["evidence_refs"], ["student:STU-1"])
		self.assertEqual(evidence["student_360"]["provenance_ids"], ["student:STU-1"])
		self.assertNotIn("student_name", str(evidence))
		self.assertNotIn("phone", str(evidence))

	def test_school_activity_outcome_provenance_resolves_to_its_activity(self):
		with patch("crm.fcrm.intelligence_runs.frappe.db.exists", return_value=True), patch(
			"crm.fcrm.intelligence_runs.frappe.has_permission", return_value=True
		):
			self.assertTrue(intelligence_runs._claim_visible(["activity:SAC-1", "outcome:SAC-1"]))
