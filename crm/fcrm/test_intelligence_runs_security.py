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

	def test_student_source_digest_binds_bounded_analysis_input(self):
		first = {"signals": {"score": 70, "interaction_history": []}, "provenance_ids": ["student:STU-1"]}
		second = {"signals": {"score": 71, "interaction_history": []}, "provenance_ids": ["student:STU-1"]}
		with patch("crm.fcrm.intelligence_runs.frappe.db.get_value", return_value=9), patch(
			"crm.fcrm.intelligence_runs._student_stage_evidence", side_effect=[{"student_360": first}, {"student_360": second}]
		):
			revision_a, digest_a = intelligence_runs._source("student", "STU-1")
			revision_b, digest_b = intelligence_runs._source("student", "STU-1")
		self.assertEqual((revision_a, revision_b), ("9", "9"))
		self.assertNotEqual(digest_a, digest_b)

	def test_student_source_digest_binds_student_stage(self):
		first = {"signals": {"student_stage": "New"}, "provenance_ids": ["student:STU-1"]}
		second = {"signals": {"student_stage": "Connected"}, "provenance_ids": ["student:STU-1"]}
		with patch("crm.fcrm.intelligence_runs.frappe.db.get_value", return_value=9), patch(
			"crm.fcrm.intelligence_runs._student_stage_evidence", side_effect=[{"student_360": first}, {"student_360": second}]
		):
			_, digest_a = intelligence_runs._source("student", "STU-1")
			_, digest_b = intelligence_runs._source("student", "STU-1")
		self.assertNotEqual(digest_a, digest_b)

	def test_student_stage_evidence_is_minimized_and_uses_resolvable_provenance(self):
		row = {"student_stage": "Connected", "interest_level": "High", "fit_level": "High", "score_input_revision": 9, "applied_score_input_revision": 9}
		with patch(
			"crm.fcrm.intelligence_runs.frappe.db.get_value", return_value=row
		), patch("crm.fcrm.intelligence_runs.frappe.get_all", return_value=[]), patch(
			"crm.fcrm.intelligence_runs.frappe.db.table_exists", return_value=True
		):
			evidence = intelligence_runs._student_stage_evidence("STU-1", "9")
		self.assertEqual(set(evidence), {"student_360"})
		self.assertEqual(evidence["student_360"]["provenance_ids"], ["student:STU-1"])
		self.assertEqual(evidence["student_360"]["signals"]["student_stage"], "Connected")
		self.assertNotIn("enrollment_status", evidence["student_360"]["signals"])
		self.assertNotIn("lifecycle_stage", evidence["student_360"]["signals"])
		self.assertNotIn("student_name", str(evidence))
		self.assertNotIn("phone", str(evidence))

	def test_student_evidence_stage_rejects_removed_status_values(self):
		self.assertEqual(intelligence_runs._canonical_student_stage("Connected"), "Connected")
		self.assertIsNone(intelligence_runs._canonical_student_stage("Converted"))

	def test_student_intelligence_refs_are_bounded_and_keep_each_evidence_section(self):
		refs = intelligence_runs._bounded_provenance_refs(
			"student:STU-1",
			(
				[f"score:S-{index}" for index in range(12)],
				[f"interaction:I-{index}" for index in range(20)],
				[f"application:A-{index}" for index in range(8)],
				[f"guardian:G-{index}" for index in range(8)],
			),
			intelligence_runs.MAX_STUDENT_INTELLIGENCE_REFS,
		)
		self.assertEqual(len(refs), intelligence_runs.MAX_STUDENT_INTELLIGENCE_REFS)
		self.assertEqual(len(refs), len(set(refs)))
		self.assertEqual(refs[0], "student:STU-1")
		self.assertEqual(
			{ref.split(":", 1)[0] for ref in refs[1:]},
			{"score", "interaction", "application", "guardian"},
		)

	def test_student_evidence_history_and_authority_refs_share_one_bound(self):
		row = {
			"student_stage": "Connected",
			"score_input_revision": 9,
			"applied_score_input_revision": 9,
		}
		rows_by_doctype = {
			"CRM Score History": [
				{"name": f"S-{index}", "scoring_time": "2026-01-01"}
				for index in range(12)
			],
			"CRM Interaction": [
				{
					"name": f"I-{index}",
					"interaction_datetime": "2026-01-01",
					"source_verified": 1,
				}
				for index in range(20)
			],
			"CRM Intent": [],
			"CRM Admission Application": [{"name": f"A-{index}"} for index in range(8)],
			"CRM Student Guardian": [{"name": f"G-{index}"} for index in range(8)],
		}

		def fake_get_all(doctype, **_kwargs):
			return rows_by_doctype[doctype]

		with (
			patch("crm.fcrm.intelligence_runs.frappe.db.get_value", return_value=row),
			patch("crm.fcrm.intelligence_runs.frappe.get_all", side_effect=fake_get_all),
			patch("crm.fcrm.intelligence_runs.frappe.get_doc", return_value={"details": []}),
			patch("crm.fcrm.intelligence_runs.frappe.db.table_exists", return_value=True),
		):
			payload = intelligence_runs._student_stage_evidence("STU-1", "9")["student_360"]

		sections = ("score_history", "interaction_history", "applications", "guardian_signals")
		signal_refs = {
			ref
			for section in sections
			for item in payload["signals"][section]
			for ref in item["provenance_ids"]
		}
		authority_ids = {ref["evidence_id"] for ref in payload["intelligence_refs"]}
		self.assertEqual(
			[len(payload["signals"][section]) for section in sections],
			[4, 4, 4, 3],
		)
		self.assertLessEqual(len(authority_ids), intelligence_runs.MAX_STUDENT_INTELLIGENCE_REFS)
		self.assertTrue({f"{ref}:9" for ref in signal_refs}.issubset(authority_ids))

	def test_school_activity_outcome_provenance_resolves_to_its_activity(self):
		with patch("crm.fcrm.intelligence_runs.frappe.db.exists", return_value=True), patch(
			"crm.fcrm.intelligence_runs.frappe.has_permission", return_value=True
		):
			self.assertTrue(intelligence_runs._claim_visible(["activity:SAC-1", "outcome:SAC-1"]))
