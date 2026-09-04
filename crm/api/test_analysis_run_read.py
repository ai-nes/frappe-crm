"""Contract tests for the Student 360 Sales dashboard reader."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import analysis_run_read


class TestStudent360Dashboard(FrappeTestCase):
	@patch("crm.api.analysis_run_read._score", return_value={"items": [{"key": key, "value": None, "trend": {"direction": "unknown", "delta": None}, "contributors": []} for key in ("fit", "interaction", "intent", "total")], "explanation": {"text": "", "evidence_refs": []}})
	@patch("crm.api.analysis_run_read._journal", return_value={"inbound": [], "outbound": []})
	@patch("crm.api.analysis_run_read.request_run")
	@patch("crm.api.analysis_run_read._stages")
	@patch("crm.api.analysis_run_read._source", return_value=("4", "a" * 64))
	@patch("crm.api.analysis_run_read._student_scope", return_value="STU-1")
	def test_returns_fixed_dashboard_blocks(self, _scope, _source, stages, request, _journal, _score):
		stages.side_effect = [[], [], [], []]
		payload = analysis_run_read.get_student_360(student="STU-1", request=True)
		self.assertEqual(payload["student_id"], "STU-1")
		self.assertEqual(payload["snapshot_schema_version"], "student-360-snapshot-v1")
		self.assertEqual(payload["snapshot_status"], "NONE")
		self.assertEqual(payload["analysis_status"], "IDLE")
		self.assertEqual(set(payload), {"student_id", "snapshot_schema_version", "snapshot_status", "analysis_status", "analyzed_at", "advisory_signals", "interaction_journal", "score_overview", "risks", "opportunity_signals", "recent_changes"})
		self.assertEqual(set(payload["score_overview"]), {"fit", "interaction", "intent", "total", "band", "trend", "summary", "contributors"})
		self.assertEqual(payload["score_overview"]["trend"]["direction"], "UNKNOWN")
		request.assert_called_once()

	@patch("crm.api.analysis_run_read._score", return_value={"items": [{"key": key, "value": None, "trend": {"direction": "unknown", "delta": None}, "contributors": []} for key in ("fit", "interaction", "intent", "total")], "explanation": {"text": "", "evidence_refs": []}})
	@patch("crm.api.analysis_run_read._journal", return_value={"inbound": [], "outbound": []})
	@patch("crm.api.analysis_run_read.request_run")
	@patch("crm.api.analysis_run_read._stages")
	@patch("crm.api.analysis_run_read._source", return_value=("4", "b" * 64))
	@patch("crm.api.analysis_run_read._student_scope", return_value="STU-1")
	def test_failed_refresh_keeps_latest_success(self, _scope, _source, stages, request, _journal, _score):
		completed = {"name": "SNAP-1", "status": "completed", "expected_source_digest": "old", "modified": None, "claims": [], "report_json": None}
		failed = {"name": "RUN-2", "status": "failed", "expected_source_digest": "b" * 64, "modified": None}
		stages.side_effect = [[failed], [completed, failed]]
		payload = analysis_run_read.get_student_360(student="STU-1")
		self.assertEqual(payload["snapshot_status"], "NONE")
		self.assertEqual(payload["analysis_status"], "FAILED")
		self.assertIsNone(payload["analyzed_at"])
		request.assert_not_called()

	@patch("crm.api.analysis_run_read._score", return_value={"items": [{"key": key, "value": 10, "contributors": []} for key in ("fit", "interaction", "intent", "total")], "band": "LOW", "trend": {"direction": "FLAT", "delta": 0}, "explanation": {"text": "", "evidence_refs": []}})
	@patch("crm.api.analysis_run_read._journal", return_value={"inbound": [], "outbound": []})
	@patch("crm.api.analysis_run_read._snapshot", return_value={"generated_at": "2026-09-05T01:00:00+00:00", "advisory_signals": [{"title": "Tín hiệu", "summary": "Có căn cứ.", "evidence_refs": ["student:STU-1"]}], "risks": [], "opportunity_signals": [], "recent_changes": []})
	@patch("crm.api.analysis_run_read._stages")
	@patch("crm.api.analysis_run_read._source", return_value=("4", "current-digest"))
	@patch("crm.api.analysis_run_read._student_scope", return_value="STU-1")
	def test_data_change_marks_existing_snapshot_stale_without_requesting_ai(self, _scope, _source, stages, _snapshot, _journal, _score):
		stages.side_effect = [
			[{"name": "SNAP-1", "status": "completed", "expected_source_digest": "old-digest"}],
			[{"name": "SNAP-1", "status": "completed", "expected_source_digest": "old-digest"}],
		]
		payload = analysis_run_read.get_student_360(student="STU-1")
		self.assertEqual(payload["snapshot_status"], "STALE")
		self.assertEqual(payload["analysis_status"], "IDLE")
