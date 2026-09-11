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
		self.assertEqual(set(payload), {"student_id", "snapshot_schema_version", "snapshot_status", "analysis_status", "analyzed_at", "student_stage", "source_modified", "advisory_signals", "interaction_journal", "score_overview", "source_revision", "risks", "opportunity_signals", "recent_changes"})
		self.assertEqual(set(payload["score_overview"]), {"fit", "interaction", "intent", "total", "as_of", "band", "trend", "summary", "contributors"})
		self.assertEqual(payload["score_overview"]["trend"]["direction"], "UNKNOWN")
		self.assertIsNone(payload["score_overview"]["as_of"])
		self.assertEqual(payload["source_revision"], "4")
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

	@patch("crm.api.analysis_run_read._score", return_value={"items": [{"key": key, "value": None, "contributors": []} for key in ("fit", "interaction", "intent", "total")], "band": "LOW", "trend": {"direction": "FLAT", "delta": 0}, "explanation": {"text": "", "evidence_refs": []}})
	@patch("crm.api.analysis_run_read._journal", return_value={"inbound": [], "outbound": []})
	@patch("crm.api.analysis_run_read._snapshot", return_value={
		"generated_at": "2026-09-05T01:00:00+00:00",
		"advisory_signals": [], "risks": [], "opportunity_signals": [], "recent_changes": [],
		"history_coverage": {"interaction_history": {"included_count": 1, "omitted_count": 0, "state": "available", "coverage_reason": None, "oldest_included": "2026-09-05", "newest_included": "2026-09-05"}},
		"finding_coverage": {"emitted": 3, "unmapped": 1},
	})
	@patch("crm.api.analysis_run_read._stages")
	@patch("crm.api.analysis_run_read._source", return_value=("4", "current-digest"))
	@patch("crm.api.analysis_run_read._student_scope", return_value="STU-1")
	def test_v2_snapshot_advertises_schema_and_exposes_coverage(self, _scope, _source, stages, _snapshot, _journal, _score):
		stages.side_effect = [
			[{"name": "SNAP-1", "status": "completed", "expected_source_digest": "current-digest"}],
			[{"name": "SNAP-1", "status": "completed", "expected_source_digest": "current-digest"}],
		]
		payload = analysis_run_read.get_student_360(student="STU-1")
		self.assertEqual(payload["snapshot_schema_version"], "student-360-snapshot-v2")
		self.assertIn("history_coverage", payload)
		self.assertEqual(payload["history_coverage"]["interaction_history"]["state"], "available")
		self.assertEqual(payload["finding_coverage"], {"emitted": 3, "unmapped": 1})


class TestStudent360StageAndScoreOmission(FrappeTestCase):
	@patch("crm.api.analysis_run_read._score", return_value={"as_of": None, "items": [{"key": key, "value": None, "trend": {"direction": "unknown", "delta": None}, "contributors": []} for key in ("fit", "interaction", "intent", "total")], "explanation": {"text": "", "evidence_refs": []}, "omitted_reason": "permission_denied"})
	@patch("crm.api.analysis_run_read._journal", return_value={"inbound": [], "outbound": []})
	@patch("crm.api.analysis_run_read._stages", return_value=[])
	@patch("crm.api.analysis_run_read._source", return_value=(None, "a" * 64))
	def test_payload_carries_real_student_stage_and_propagates_score_omission(self, _source, _stages, _journal, _score):
		import frappe

		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc(
			{"doctype": "CRM Student", "full_name": "_Test Stage Student", "phone": phone, "student_stage": "Qualified"}
		).insert(ignore_permissions=True)
		try:
			with patch("crm.api.analysis_run_read._student_scope", return_value=student.name):
				payload = analysis_run_read.get_student_360(student=student.name)
			self.assertEqual(payload["student_stage"], "Qualified")
			self.assertIsNotNone(payload["source_modified"])
			self.assertEqual(payload["score_overview"]["omitted_reason"], "permission_denied")
		finally:
			frappe.delete_doc("CRM Student", student.name, ignore_permissions=True, force=True)


class TestStudent360PerSourcePermissions(FrappeTestCase):
	"""The CRM Student read check must not stand in for the caller's own
	CRM Interaction / CRM Score History permission when rows are materialized."""

	def test_journal_and_score_read_through_the_callers_permission(self):
		with patch("crm.api.analysis_run_read.frappe.get_list", return_value=[]) as get_list, patch(
			"crm.api.analysis_run_read.frappe.get_all"
		) as get_all:
			journal = analysis_run_read._journal("STU-1")
			score = analysis_run_read._score("STU-1")
		get_all.assert_not_called()
		self.assertEqual([call.args[0] for call in get_list.call_args_list], ["CRM Interaction", "CRM Score History"])
		self.assertEqual(journal["inbound"], [])
		self.assertIsNone(score["as_of"])

	def test_user_without_interaction_read_gets_an_empty_journal(self):
		import frappe

		user = "_test_student360_noperm@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "No Perm", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.set_user(user)
		try:
			self.assertFalse(frappe.has_permission("CRM Interaction", "read", user=user))
			journal = analysis_run_read._journal("STU-1")
			self.assertEqual((journal["inbound"], journal["outbound"]), ([], []))
			self.assertEqual(journal["omitted_reason"], "permission_denied")
		finally:
			frappe.set_user("Administrator")

	def test_user_without_score_history_read_gets_an_empty_score_with_reason(self):
		import frappe

		user = "_test_student360_noscoreperm@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc({"doctype": "User", "email": user, "first_name": "No Score Perm", "send_welcome_email": 0}).insert(ignore_permissions=True)
		frappe.set_user(user)
		try:
			self.assertFalse(frappe.has_permission("CRM Score History", "read", user=user))
			score = analysis_run_read._score("STU-1")
			self.assertIsNone(score["as_of"])
			self.assertEqual(score["omitted_reason"], "permission_denied")
		finally:
			frappe.set_user("Administrator")

