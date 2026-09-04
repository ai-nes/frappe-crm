"""Cross-repository Student 360 snapshot v1 contract tests."""

import json
from pathlib import Path
from unittest import TestCase

from crm.fcrm.intelligence_runs import _validate_student_awareness_report


FIXTURE = Path(__file__).parent / "fixtures" / "student-360-snapshot-v1.json"


class TestStudent360SnapshotContract(TestCase):
	def test_shared_fixture_uses_only_the_canonical_v1_shape(self):
		report = json.loads(FIXTURE.read_text(encoding="utf-8"))
		_validate_student_awareness_report(report)
		self.assertEqual(set(report), {"advisory_signals", "risks", "opportunity_signals", "recent_changes"})

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
