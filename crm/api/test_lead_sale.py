from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import lead_sale


class TestLeadSaleOverview(FrappeTestCase):
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
				"lifecycle_stage": "MQL",
				"owner_staff": "STAFF-1",
				"creation": "2026-09-05 08:00:00",
			},
			{
				"name": "STU-2",
				"student_name": "Hai",
				"lifecycle_stage": "Lead",
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
			patch.object(lead_sale, "_viewer", return_value={"id": "lead@example.com", "displayName": "Lead Sales"}),
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
