from datetime import date, datetime
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
		reason = lead_sale._assignment_reason({}, "error", None, {"last_error_code": "UNKNOWN_ROUTING_CODE"})

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
			patch.object(
				lead_sale,
				"_now",
				return_value=datetime(2026, 9, 5, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
			),
		):
			response = lead_sale.run_student_assignment_pipeline(admissionYear="2026", limit=10)

		self.assertEqual(response["run"]["checked"], 1)
		self.assertEqual(response["run"]["assigned"], 1)
		self.assertEqual(response["results"][0]["student"], "STU-POOL")
		_process.assert_called_once_with("REQ-1")

	def test_student_status_is_exhaustive_and_matches_active_kpi(self):
		status = lead_sale._build_student_status(
			[
				{"id": "STU-1", "student_stage": "Attempting"},
				{"id": "STU-2", "student_stage": "Connected"},
				{"id": "STU-3", "student_stage": "Qualified"},
			]
		)

		self.assertEqual(status["total"], 3)
		self.assertEqual(sum(item["count"] for item in status["items"]), status["total"])
		self.assertAlmostEqual(sum(item["share"] for item in status["items"]), 99.9, places=1)

	def test_new_enter_is_an_enrollment_outcome_and_not_an_active_record(self):
		record = {"id": "STU-1", "student_stage": "New Enter"}

		self.assertTrue(lead_sale._dashboard_is_enrolled(record))
		self.assertFalse(lead_sale._is_active_pipeline_record(record))

	def test_new_enter_counts_as_won_for_the_responsible_staff_member(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		records = [
			{
				"id": "STU-1",
				"owner_staff": "STAFF-1",
				"student_stage": "New Enter",
				"creation": "2026-09-05 08:00:00",
			}
		]

		with (
			patch.object(lead_sale, "_team_staff_ids", return_value=["STAFF-1"]),
			patch.object(
				lead_sale,
				"_get_list",
				return_value=[{"name": "STAFF-1", "full_name": "Sale 1"}],
			),
		):
			members = lead_sale._dashboard_members(
				[{"name": "TEAM-1"}],
				records,
				{"STU-1": "qualified"},
				{"STU-1": 0},
				set(),
				{},
				date(2026, 9, 1),
				date(2026, 9, 5),
				datetime(2026, 9, 5, 10, 0, tzinfo=timezone),
				timezone,
				{"STU-1": "STAFF-1"},
				set(),
			)

		self.assertEqual(members[0]["enrollment"], 1)
		self.assertEqual(members[0]["closedOpportunities"], 1)
		self.assertEqual(members[0]["wonOpportunities"], 1)

	def test_priority_queue_keeps_assigned_owner_when_rep_roster_does_not_include_owner(self):
		record = {
			"id": "STU-OWNER-OUTSIDE-ROSTER",
			"name": "Student outside rep roster",
			"owner_staff": "Trưởng nhóm Tư vấn",
			"student_stage": "Attempting",
			"stages": set(),
			"creation": "2026-09-09 08:00:00",
		}

		priority_queue = lead_sale._dashboard_priority_queue(
			[record],
			{"STU-OWNER-OUTSIDE-ROSTER": "attempting"},
			{"STU-OWNER-OUTSIDE-ROSTER": 15},
			set(),
			{},
			{},
			[],
			{},
			{},
			datetime(2026, 9, 25, 10, 0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")),
		)

		self.assertEqual(priority_queue[0]["owner"], "Trưởng nhóm Tư vấn")

	def test_dashboard_detail_records_keep_each_drilldown_group_distinct(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		as_of = datetime(2026, 9, 25, 10, 0, tzinfo=timezone)
		records = [
			{
				"id": "STU-OVERDUE",
				"name": "Hồ sơ quá hạn",
				"owner_staff": "STAFF-1",
				"stages": {"contacted"},
			},
			{
				"id": "STU-UNASSIGNED",
				"name": "Hồ sơ chưa phân công",
				"owner_staff": None,
				"stages": set(),
			},
			{
				"id": "STU-DUE",
				"name": "Hồ sơ cần liên hệ",
				"owner_staff": "STAFF-1",
				"stages": {"contacted"},
			},
			{
				"id": "STU-ENROLLED",
				"name": "Hồ sơ đã nhập học",
				"owner_staff": "STAFF-1",
				"stages": {"admitted"},
			},
		]
		rows = lead_sale._dashboard_detail_records(
			records,
			{"STU-ENROLLED"},
			{
				"STU-OVERDUE": "connected",
				"STU-UNASSIGNED": "new",
				"STU-DUE": "attempting",
				"STU-ENROLLED": "qualified",
			},
			{
				"STU-OVERDUE": 11,
				"STU-UNASSIGNED": 7,
				"STU-DUE": 1,
				"STU-ENROLLED": 2,
			},
			{"STU-OVERDUE", "STU-UNASSIGNED"},
			{},
			{},
			[],
			{"STAFF-1": "Sale 1"},
			{
				"STU-OVERDUE": datetime(2026, 9, 20, 10, 0, tzinfo=timezone),
				"STU-DUE": datetime(2026, 9, 25, 15, 0, tzinfo=timezone),
			},
			date(2026, 9, 25),
			as_of,
		)

		by_id = {row["id"]: row for row in rows}
		self.assertEqual(by_id["STU-OVERDUE"]["actionIds"], ["overdue", "aging"])
		self.assertEqual(by_id["STU-UNASSIGNED"]["actionIds"], ["unassigned", "aging"])
		self.assertEqual(by_id["STU-DUE"]["actionIds"], ["due-today"])
		self.assertEqual(by_id["STU-ENROLLED"]["recordType"], "enrolled")
		self.assertIsNone(by_id["STU-ENROLLED"]["agingBucketId"])

	def test_trend_contract_has_four_week_and_three_month_buckets(self):
		trend = lead_sale._build_result_trend(
			[], datetime(2026, 9, 5).date(), "4w", ZoneInfo("Asia/Ho_Chi_Minh")
		)

		self.assertEqual(trend["defaultRange"], "4w")
		self.assertEqual(len(trend["ranges"]["4w"]["points"]), 4)
		self.assertEqual(len(trend["ranges"]["3m"]["points"]), 3)
		self.assertEqual(trend["ranges"]["3m"]["from"], "2026-06-05")

	def test_dashboard_age_uses_current_stage_entry_time(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		record = {
			"id": "STU-1",
			"creation": "2026-08-01 08:00:00",
			"stage_entered_at": {"qualified": datetime(2026, 9, 3, 8, 0)},
		}

		age = lead_sale._dashboard_age_days(
			record, "qualified", datetime(2026, 9, 5, 10, 0, tzinfo=timezone), timezone
		)

		self.assertEqual(age, 2)

	def test_dashboard_stage_conversion_uses_stage_history(self):
		records = [
			{
				"id": "STU-1",
				"stage_history": [
					{"stage": "new"},
					{"stage": "attempting"},
					{"stage": "connected"},
				],
			},
			{"id": "STU-2", "stage_history": [{"stage": "new"}, {"stage": "attempting"}]},
		]
		stage_by_record = {"STU-1": "connected", "STU-2": "attempting"}
		stats = lead_sale._dashboard_stage_stats(
			records, stage_by_record, {"STU-1": 1, "STU-2": 1}, set()
		)

		self.assertEqual(stats["attempting"]["nextStepConversion"], 50)

	def test_dashboard_stage_conversion_only_counts_ordered_transitions(self):
		records = [
			{"id": "STU-1", "stage_history": [{"stage": "new"}, {"stage": "attempting"}]},
			{
				"id": "STU-2",
				"stage_history": [{"stage": "new"}, {"stage": "attempting"}, {"stage": "connected"}],
			},
			{"id": "STU-3", "stage_history": [{"stage": "new"}, {"stage": "connected"}]},
		]
		stage_by_record = {"STU-1": "attempting", "STU-2": "connected", "STU-3": "connected"}
		stats = lead_sale._dashboard_stage_stats(
			records,
			stage_by_record,
			{"STU-1": 1, "STU-2": 1, "STU-3": 1},
			set(),
		)

		self.assertEqual(stats["attempting"]["nextStepConversion"], 50)

	def test_dashboard_stage_conversion_does_not_infer_unrecorded_previous_stages(self):
		record = {
			"id": "STU-1",
			"stage_history": [{"stage": "new"}, {"stage": "qualified"}],
		}

		self.assertFalse(lead_sale._dashboard_reached_stage(record, "connected", {"STU-1": "qualified"}))

	def test_dashboard_trend_uses_canonical_stage_counts(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		records = [
			{
				"id": "STU-1",
				"student_stage": "Attempting",
				"creation": "2026-09-08 08:00:00",
				"stage_entered_at": {
					"new": datetime(2026, 9, 8, 8, 0),
					"attempting": datetime(2026, 9, 9, 8, 0),
				},
			},
			{
				"id": "STU-2",
				"student_stage": "Connected",
				"creation": "2026-09-08 08:00:00",
				"stage_entered_at": {
					"new": datetime(2026, 9, 8, 8, 0),
					"attempting": datetime(2026, 9, 9, 8, 0),
					"connected": datetime(2026, 9, 10, 8, 0),
				},
			},
		]

		trend = lead_sale._dashboard_trend(records, datetime(2026, 9, 17).date(), "4w", timezone)

		self.assertEqual(
			trend[2]["stageCounts"],
			{"new": 2, "attempting": 2, "connected": 1, "qualified": 0},
		)

	def test_dashboard_target_is_unavailable_without_an_approved_team_scope(self):
		with (
			patch.object(lead_sale.frappe.db, "table_exists", return_value=True),
			patch.object(lead_sale, "_get_list", return_value=[]),
		):
			target = lead_sale._dashboard_target("2026", ["TEAM-1"], datetime(2026, 9, 5).date())

		self.assertIsNone(target)

	def test_dashboard_follow_up_counts_one_deadline_per_student(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		records = [{"id": "STU-1", "next_follow_up": "2026-09-02 08:00:00"}]
		tasks = [
			{"student_id": "STU-1", "due_at": "2026-09-01 08:00:00", "status": "Open"},
			{"student_id": "STU-1", "due_at": "2026-09-04 08:00:00", "status": "Open"},
		]

		deadlines = lead_sale._dashboard_follow_up_deadlines(
			records,
			{"STU-1": [{"next_follow_up": "2026-09-03 08:00:00"}]},
			tasks,
			timezone,
		)

		self.assertEqual(len(deadlines), 1)
		self.assertEqual(deadlines["STU-1"].date().isoformat(), "2026-09-01")

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
			patch.object(
				lead_sale,
				"_require_access",
				return_value={"user": "lead@example.com", "profile": "lead_sales"},
			),
			patch.object(lead_sale, "_resolve_admission_year", return_value="2026"),
			patch.object(
				lead_sale, "_resolve_teams", return_value=[{"name": "TEAM-1", "team_name": "Đội Sale"}]
			),
			patch.object(lead_sale, "_now", return_value=datetime(2026, 9, 5, 10, 0, tzinfo=timezone)),
			patch.object(
				lead_sale, "_viewer", return_value={"id": "lead@example.com", "displayName": "Lead Sale"}
			),
			patch.object(lead_sale, "_load_students", return_value=students),
			patch.object(lead_sale.sale_overview, "_load_contacts", return_value=[]),
			patch.object(lead_sale.sale_overview, "_load_applications", return_value=[]),
			patch.object(lead_sale.sale_overview, "_load_interactions", return_value=interactions),
			patch.object(lead_sale.sale_overview, "_load_tasks", return_value=[]),
			patch.object(lead_sale, "_build_team_performance", return_value=[]),
		):
			response = lead_sale.get_lead_sale_overview(admissionYear="2026", date="2026-09-05")

		self.assertEqual(
			{item["id"]: item["value"] for item in response["kpis"]},
			{
				"active": 1,
				"new": 1,
				"unassigned": 1,
				"needs-action": 0,
				"overdue": 0,
				"documents": 0,
			},
		)
		self.assertEqual(response["studentStatus"]["total"], 1)
		self.assertEqual(response["studentStatus"]["total"], response["kpis"][0]["value"])
		self.assertEqual(len(response["resultTrend"]["ranges"]["4w"]["points"]), 4)
		self.assertEqual(len(response["resultTrend"]["ranges"]["3m"]["points"]), 3)
		self.assertEqual(response["meta"]["team"]["id"], "TEAM-1")
		self.assertIn("STU-1", [row["id"] for row in response["dashboard"]["detailRecords"]])

	def test_full_board_lead_sale_does_not_require_team_membership(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		students = [
			{
				"name": "STU-GLOBAL",
				"student_name": "Hồ sơ toàn hệ thống",
				"processing_status": "PROCESSING",
				"resolution": "PENDING",
				"owner_staff": None,
				"assigned_to": None,
				"creation": "2026-09-05 08:00:00",
			}
		]
		with (
			patch.object(
				lead_sale,
				"_require_access",
				return_value={"user": "leadsale@gmail.com", "profile": "lead_sales"},
			),
			patch.object(lead_sale, "can_read_full_lead_board", return_value=True),
			patch.object(lead_sale, "_resolve_all_sales_teams", return_value=[]),
			patch.object(lead_sale, "_resolve_teams", side_effect=AssertionError("team scope must be skipped")),
			patch.object(lead_sale, "_resolve_admission_year", return_value="2026"),
			patch.object(lead_sale, "_now", return_value=datetime(2026, 9, 5, 10, 0, tzinfo=timezone)),
			patch.object(
				lead_sale, "_viewer", return_value={"id": "leadsale@gmail.com", "displayName": "Lead Sale"}
			),
			patch.object(lead_sale, "_load_students", return_value=students) as load_students,
			patch.object(lead_sale.sale_overview, "_load_contacts", return_value=[]),
			patch.object(lead_sale.sale_overview, "_load_applications", return_value=[]),
			patch.object(lead_sale.sale_overview, "_load_interactions", return_value=[]),
			patch.object(lead_sale.sale_overview, "_load_tasks", return_value=[]),
			patch.object(lead_sale, "_build_team_performance", return_value=[]),
		):
			response = lead_sale.get_lead_sale_overview(admissionYear="2026", date="2026-09-05")

		self.assertIsNone(load_students.call_args.args[2])
		self.assertTrue(load_students.call_args.kwargs["unrestricted"])
		self.assertEqual(response["meta"]["team"], {"id": "all", "name": "Toàn bộ đội Sale"})
		self.assertNotIn("team.membership_not_found", response["meta"]["warnings"])
		self.assertEqual(response["kpis"][2]["value"], 1)

	def test_unrestricted_student_reader_bypasses_team_query_scope(self):
		with (
			patch.object(lead_sale.frappe.db, "table_exists", return_value=True),
			patch.object(lead_sale.frappe, "get_all", return_value=[{"name": "STU-GLOBAL"}]) as get_all,
			patch.object(lead_sale.frappe, "get_list") as get_list,
		):
			rows = lead_sale._load_students(
				"2026", [], teams=None, include_closed=True, unrestricted=True
			)

		self.assertEqual([row["name"] for row in rows], ["STU-GLOBAL"])
		get_all.assert_called_once()
		get_list.assert_not_called()
