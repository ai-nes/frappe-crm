from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import lead_sale


class TestLeadSaleOverview(FrappeTestCase):
	def test_assignment_reason_translates_routing_code(self):
		reason = lead_sale._assignment_reason(
			{}, "error", None, {"last_error_code": "TEAM_NOT_FOUND_FOR_PROVINCE"}
		)

		self.assertEqual(reason, "Chưa có Team đang phụ trách tỉnh của Student.")
		self.assertNotIn("TEAM_NOT_FOUND_FOR_PROVINCE", reason)

	def test_assignment_reason_hides_unknown_routing_code(self):
		reason = lead_sale._assignment_reason(
			{}, "error", None, {"last_error_code": "UNKNOWN_ROUTING_CODE"}
		)

		self.assertNotIn("UNKNOWN_ROUTING_CODE", reason)
		self.assertIn("kiểm tra cấu hình Team", reason)

	@patch.object(lead_sale, "get_student_assignment_workspace")
	def test_lead_workspace_alias_drops_frappe_cmd(self, get_workspace):
		get_workspace.return_value = {"ok": True}

		response = lead_sale.get_lead_assignment_workspace(
			cmd="crm.api.lead_sale.get_lead_assignment_workspace",
			admissionYear="2026",
			filter="review",
		)

		self.assertEqual(response, {"ok": True})
		get_workspace.assert_called_once_with(admissionYear="2026", filter="review")

	def test_pipeline_candidates_are_pool_owned_and_request_scoped(self):
		students = [
			{"name": "STU-POOL", "owning_pool": "POOL-1", "owner_staff": None, "assigned_to": None},
			{"name": "STU-OWNER", "owning_pool": None, "owner_staff": "STAFF-1", "assigned_to": "STAFF-1"},
			{"name": "STU-APPLIED", "owning_pool": "POOL-1", "owner_staff": None, "assigned_to": None},
			{"name": "STU-NO-POOL", "owning_pool": None, "owner_staff": None, "assigned_to": None},
		]
		requests = [
			{"student": "STU-POOL", "status": "pending"},
			{"student": "STU-APPLIED", "status": "applied"},
		]

		candidates = lead_sale._assignment_pipeline_candidates(students, requests, limit=10)

		self.assertEqual([row["student"]["name"] for row in candidates], ["STU-POOL"])
		self.assertEqual(candidates[0]["request"]["status"], "pending")

	@patch("crm.fcrm.student_routing.process_routing_request")
	@patch.object(lead_sale, "get_student_assignment_workspace")
	@patch.object(lead_sale.frappe, "get_all")
	@patch.object(lead_sale.frappe.db, "table_exists", return_value=True)
	def test_pipeline_endpoint_processes_only_current_pool_scope(
		self, _table_exists, get_all, get_workspace, _process
	):
		students = [
			{
				"name": "STU-POOL",
				"owning_pool": "POOL-1",
				"owning_team": "TEAM-1",
				"owner_staff": None,
				"assigned_to": None,
			},
			{
				"name": "STU-OWNER",
				"owning_pool": None,
				"owning_team": None,
				"owner_staff": "STAFF-1",
				"assigned_to": "STAFF-1",
			},
		]
		get_all.return_value = [{"name": "REQ-1", "student": "STU-POOL", "status": "pending"}]
		_process.return_value = {"status": "applied", "request": "REQ-1", "owner_staff": "STAFF-2", "tier": 1}
		get_workspace.return_value = {
			"meta": {},
			"summary": {"received": 2, "assigned": 1},
			"health": {},
			"workflow": {"steps": []},
		}

		with (
			patch.object(lead_sale, "_require_assignment_access", return_value={"user": "lead@example.com"}),
			patch.object(lead_sale, "_parse_timezone", return_value=ZoneInfo("Asia/Ho_Chi_Minh")),
			patch.object(lead_sale, "_resolve_admission_year", return_value="2026"),
			patch.object(lead_sale, "_assignment_scope", return_value={"team_ids": ["TEAM-1"]}),
			patch.object(lead_sale, "_assignment_load_students", return_value=students),
			patch.object(lead_sale, "_now", return_value=datetime(2026, 9, 5, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))),
		):
			response = lead_sale.run_student_assignment_pipeline(admissionYear="2026", limit=10)

		self.assertEqual(response["run"]["checked"], 1)
		self.assertEqual(response["run"]["assigned"], 1)
		self.assertEqual(response["results"][0]["student"], "STU-POOL")
		_process.assert_called_once_with("REQ-1")

	def test_student_status_is_exhaustive_and_matches_active_kpi(self):
		status = lead_sale._build_student_status(
			[
				{"id": "STU-1", "status": "consulting"},
				{"id": "STU-2", "status": "waiting"},
				{"id": "STU-3", "status": "documents"},
			]
		)

		self.assertEqual(status["total"], 3)
		self.assertEqual(sum(item["count"] for item in status["items"]), status["total"])
		self.assertAlmostEqual(sum(item["share"] for item in status["items"]), 99.9, places=1)

	def test_trend_contract_has_four_week_and_three_month_buckets(self):
		trend = lead_sale._build_result_trend(
			[], datetime(2026, 9, 5).date(), "4w", ZoneInfo("Asia/Ho_Chi_Minh")
		)

		self.assertEqual(trend["defaultRange"], "4w")
		self.assertEqual(len(trend["ranges"]["4w"]["points"]), 4)
		self.assertEqual(len(trend["ranges"]["3m"]["points"]), 3)
		self.assertEqual(trend["ranges"]["3m"]["from"], "2026-06-05")

	def test_endpoint_uses_one_scoped_snapshot_for_kpis_status_and_trends(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		students = [
			{
				"name": "STU-1",
				"student_name": "Một",
				"processing_status": "PROCESSING",
				"resolution": "PENDING",
				"owner_staff": "STAFF-1",
				"creation": "2026-09-05 08:00:00",
			},
			{
				"name": "STU-2",
				"student_name": "Hai",
				"processing_status": "NEW",
				"resolution": "PENDING",
				"owner_staff": None,
				"creation": "2026-09-04 08:00:00",
			},
		]
		interactions = [
			{
				"student": "STU-1",
				"interaction_type": "Counseling",
				"interaction_datetime": "2026-09-05 08:30:00",
				"outcome": "Captured",
			}
		]
		with (
			patch.object(lead_sale, "_require_access", return_value={"user": "lead@example.com", "profile": "lead_sales"}),
			patch.object(lead_sale, "_resolve_admission_year", return_value="2026"),
			patch.object(lead_sale, "_resolve_teams", return_value=[{"name": "TEAM-1", "team_name": "Đội Sale"}]),
			patch.object(lead_sale, "_now", return_value=datetime(2026, 9, 5, 10, 0, tzinfo=timezone)),
			patch.object(lead_sale, "_viewer", return_value={"id": "lead@example.com", "displayName": "Lead Sale"}),
			patch.object(lead_sale, "_load_students", return_value=students),
			patch.object(lead_sale.sale_overview, "_load_contacts", return_value=[]),
			patch.object(lead_sale.sale_overview, "_load_applications", return_value=[]),
			patch.object(lead_sale.sale_overview, "_load_interactions", return_value=interactions),
			patch.object(lead_sale.sale_overview, "_load_tasks", return_value=[]),
			patch.object(lead_sale, "_build_team_performance", return_value=[]),
		):
			response = lead_sale.get_lead_sale_overview(admissionYear="2026", date="2026-09-05")

		self.assertEqual({item["id"]: item["value"] for item in response["kpis"]}, {
			"active": 1,
			"new": 1,
			"unassigned": 1,
			"needs-action": 0,
			"overdue": 0,
			"documents": 0,
		})
		self.assertEqual(response["studentStatus"]["total"], 1)
		self.assertEqual(response["studentStatus"]["total"], response["kpis"][0]["value"])
		self.assertEqual(len(response["resultTrend"]["ranges"]["4w"]["points"]), 4)
		self.assertEqual(len(response["resultTrend"]["ranges"]["3m"]["points"]), 3)
		self.assertEqual(response["meta"]["team"]["id"], "TEAM-1")
