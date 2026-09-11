"""Cross-repository Student 360 snapshot v1 contract tests."""

import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from crm.fcrm.intelligence_runs import _public_student_snapshot, _validate_student_awareness_report


FIXTURE = Path(__file__).parent / "fixtures" / "student-360-snapshot-v1.json"


class TestStudent360SnapshotContract(TestCase):
	@patch("crm.fcrm.intelligence_runs._claim_visible", return_value=True)
	def test_public_projection_accepts_canonical_v1_shape(self, _claim_visible):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		projected = _public_student_snapshot(report, claims_visible=True)
		self.assertIsNotNone(projected)

	def test_shared_fixture_uses_only_the_canonical_v1_shape(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		_validate_student_awareness_report(report)
		self.assertEqual(set(report), {"advisory_signals", "risks", "opportunity_signals", "recent_changes"})

	def test_sparse_v1_snapshot_is_valid_when_evidence_has_no_advisory_findings(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["advisory_signals"] = []
		_validate_student_awareness_report(report)

	def test_additive_v2_snapshot_validates_history_coverage(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["history_coverage"] = {
			name: {
				"included_count": 0,
				"omitted_count": 0,
				"state": "missing",
				"coverage_reason": "source_section_missing",
				"oldest_included": None,
				"newest_included": None,
			}
			for name in ("score_history", "interaction_history", "applications", "guardian_signals")
		}
		_validate_student_awareness_report(report)

	def test_history_coverage_accepts_the_producer_truncation_layer(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["history_coverage"] = {
			name: {
				"included_count": 0, "omitted_count": 0, "state": "missing",
				"coverage_reason": "source_section_missing", "oldest_included": None, "newest_included": None,
			}
			for name in ("score_history", "applications", "guardian_signals")
		}
		report["history_coverage"]["interaction_history"] = {
			"included_count": 8, "omitted_count": 29, "state": "truncated",
			"coverage_reason": "model_history_limit", "oldest_included": "2026-08-01", "newest_included": "2026-09-06",
			"source_total": 37, "producer_limit": 20,
		}
		_validate_student_awareness_report(report)
		with patch("crm.fcrm.intelligence_runs._claim_visible", return_value=True):
			projected = _public_student_snapshot(report, claims_visible=True)
		section = projected["history_coverage"]["interaction_history"]
		self.assertEqual((section["omitted_count"], section["source_total"], section["producer_limit"]), (29, 37, 20))
		self.assertNotIn("source_total", projected["history_coverage"]["score_history"])

	def test_history_coverage_rejects_a_partial_producer_layer(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["history_coverage"] = {
			name: {
				"included_count": 0, "omitted_count": 0, "state": "missing",
				"coverage_reason": "source_section_missing", "oldest_included": None, "newest_included": None,
			}
			for name in ("score_history", "interaction_history", "applications", "guardian_signals")
		}
		report["history_coverage"]["applications"]["source_total"] = 3
		with self.assertRaises(Exception):
			_validate_student_awareness_report(report)

	def test_additive_finding_coverage_is_accepted_and_projected(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["finding_coverage"] = {"emitted": 3, "unmapped": 1}
		_validate_student_awareness_report(report)
		with patch("crm.fcrm.intelligence_runs._claim_visible", return_value=True):
			projected = _public_student_snapshot(report, claims_visible=True)
		self.assertEqual(projected["finding_coverage"], {"emitted": 3, "unmapped": 1})

	def test_malformed_finding_coverage_is_rejected(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["finding_coverage"] = {"emitted": -1}
		with self.assertRaises(Exception):
			_validate_student_awareness_report(report)

	def test_legacy_report_shape_is_rejected(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["summary"] = "Không được phép"
		with self.assertRaises(Exception):
			_validate_student_awareness_report(report)

	def test_snapshot_does_not_accept_action_advice(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["advisory_signals"][0]["summary"] = "Hãy gọi cho phụ huynh để xác minh."
		with self.assertRaises(Exception):
			_validate_student_awareness_report(report)

	def test_snapshot_rejects_deep_or_english_analysis_language(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		report["advisory_signals"][0]["summary"] = "Qua phân tích toàn diện, có thể suy ra rằng hồ sơ có khả năng nhập học cao."
		with self.assertRaises(Exception):
			_validate_student_awareness_report(report)
