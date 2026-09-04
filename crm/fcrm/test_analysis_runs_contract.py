import unittest
from types import SimpleNamespace
from unittest.mock import patch

from crm.fcrm.analysis_runs import (
	canonical_request_fingerprint,
	validate_claim_set,
	validate_execution_revisions,
	validate_stage_fields,
)
from crm.fcrm.intelligence_runs import _public_stage, _validate_student_awareness_claims


class TestAnalysisRunContracts(unittest.TestCase):
	def test_request_fingerprint_is_order_independent(self):
		left = canonical_request_fingerprint(
			{"domain": "student", "target": "STU-1", "source_revision": "4", "trigger": "manual"}
		)
		right = canonical_request_fingerprint(
			{"trigger": "manual", "source_revision": "4", "target": "STU-1", "domain": "student"}
		)
		self.assertEqual(left, right)

	def test_request_fingerprint_rejects_unknown_or_unbounded_input(self):
		with self.assertRaises(ValueError):
			canonical_request_fingerprint({"domain": "student", "credential": "do-not-store"})

	def test_student_stage_cannot_be_attached_to_school_run(self):
		stage = SimpleNamespace(
			stage_kind="student_360",
			status="queued",
			stage_key="student:STU-1:4:student_360",
			parent_run="RUN-1",
			parent_run_type="CRM School Analysis Run",
		)
		with patch("crm.fcrm.analysis_runs.frappe.throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				validate_stage_fields(stage)

	def test_school_stage_has_only_school_parent(self):
		stage = SimpleNamespace(
			stage_kind="school_360",
			status="queued",
			stage_key="school:SCH-1:7:school_360",
			parent_run="RUN-1",
			parent_run_type="CRM School Analysis Run",
		)
		validate_stage_fields(stage)

	def test_analysis_run_contract_has_no_nba_child_stage(self):
		stage = SimpleNamespace(
			stage_kind="next_best_action",
			status="queued",
			stage_key="student:STU-1:4:next_best_action",
			parent_run="RUN-1",
			parent_run_type="CRM Student Analysis Run",
		)
		with patch("crm.fcrm.analysis_runs.frappe.throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				validate_stage_fields(stage)

	def test_completed_stage_requires_reproducibility_revisions(self):
		with patch("crm.fcrm.analysis_runs.frappe.throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				validate_execution_revisions("policy-2026-09", None, required=True)

	def test_non_terminal_metadata_may_omit_model_revision(self):
		validate_execution_revisions(None, None, required=False)

	def test_claim_confidence_is_preserved_and_bounded(self):
		validate_claim_set([{
			"kind": "inference", "text": "Tín hiệu tích cực.", "provenance_ids": ["student:STU-1"],
			"visibility": "shareable", "confidence": 0.8,
		}])
		with patch("crm.fcrm.analysis_runs.frappe.throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				validate_claim_set([{
					"kind": "inference", "text": "Sai confidence.", "provenance_ids": ["student:STU-1"],
					"visibility": "shareable", "confidence": 1.1,
				}])

	def test_student_claim_cannot_smuggle_action_advice(self):
		with patch("crm.fcrm.intelligence_runs.frappe.throw", side_effect=ValueError):
			with self.assertRaises(ValueError):
				_validate_student_awareness_claims([{
					"kind": "inference", "text": "Gọi phụ huynh lúc 17:00.",
					"provenance_ids": ["student:STU-1"], "visibility": "shareable",
				}])

	def test_queued_student_stage_keeps_its_actual_nonterminal_status(self):
		stage = _public_stage(
			{"name": "STAGE-1", "stage_kind": "student_360", "status": "running", "claims": []},
			student=True,
		)
		self.assertEqual(stage["status"], "running")
		self.assertIsNone(stage["terminal_reason"])
