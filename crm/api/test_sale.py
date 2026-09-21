from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import sale


class TestSaleOverview(FrappeTestCase):
	def test_student_stage_snapshot_uses_the_canonical_core_options(self):
		result = sale._build_student_stages(
			[
				{"student_stage": "New"},
				{"student_stage": "Attempting"},
				{"student_stage": "Connected"},
				{"student_stage": "Registration"},
				{"student_stage": "New Enter"},
				{"student_stage": "Disqualified"},
			]
		)

		self.assertEqual(result["total"], 6)
		self.assertEqual([item["count"] for item in result["items"]], [1, 1, 1, 0, 1, 1, 1])
		self.assertEqual(result["items"][5]["label"], "Nhập học")
		self.assertEqual(sum(item["count"] for item in result["items"]), result["total"])

	def test_student_records_use_core_students_and_interactions(self):
		students = [
			{
				"name": "STU-1",
				"full_name": "Một",
				"student_stage": "Connected",
				"creation": "2026-09-01 08:00:00",
				"first_contact_time": "2026-09-01 09:00:00",
			}
		]
		interactions = [
			{
				"student": "STU-1",
				"interaction_type": "Counseling",
				"interaction_datetime": "2026-09-02 10:00:00",
				"outcome": "connected",
			}
		]

		result = sale._build_student_records(students, interactions)

		self.assertEqual(result[0]["student_stage"], "Connected")
		self.assertEqual(result[0]["consulted_at"], datetime(2026, 9, 2, 10, 0))
		self.assertNotIn("admitted_at", result[0])
		self.assertNotIn("status", result[0])

	def test_tasks_use_server_snapshot_for_overdue_and_priority_counts(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		tasks = [
			sale._normalize_action_task(
				{
					"name": "ACTION-1",
					"objective": "Gọi lại",
					"student": "STU-1",
					"priority": "High",
					"state": "pending",
					"due_at": "2026-09-04 09:00:00",
				}
			),
			sale._normalize_action_task(
				{
					"name": "ACTION-2",
					"objective": "Nhắc lại",
					"student": "STU-1",
					"priority": "Low",
					"state": "pending",
					"due_at": "2026-09-06 09:00:00",
				}
			),
		]
		snapshot = sale._build_tasks(
			tasks,
			datetime(2026, 9, 5).date(),
			datetime(2026, 9, 5, 10, 0, tzinfo=timezone),
			timezone,
			4,
		)

		self.assertEqual(snapshot["priority"]["overdueCount"], 1)
		self.assertEqual(snapshot["summary"]["overdue"]["count"], 1)
		self.assertEqual(snapshot["summary"]["upcoming"]["count"], 1)
		self.assertEqual(snapshot["priority"]["items"][0]["id"], "CRM Action Item:ACTION-1")
		self.assertTrue(snapshot["priority"]["items"][0]["isOverdue"])

	def test_conversion_trend_contains_core_interaction_counts_only(self):
		result = sale._build_conversion_trend(
			[{"consulted_at": "2026-09-02 10:00:00"}],
			datetime(2026, 9, 5).date(),
			"4w",
			ZoneInfo("Asia/Ho_Chi_Minh"),
		)

		points = result["ranges"]["4w"]["points"]
		self.assertEqual(sum(point["consulted"] for point in points), 1)
		self.assertTrue(all("admitted" not in point for point in points))

	def test_endpoint_returns_only_core_dashboard_sections_and_scopes_students(self):
		timezone = ZoneInfo("Asia/Ho_Chi_Minh")
		as_of = datetime(2026, 9, 5, 10, 0, tzinfo=timezone)
		with (
			patch.object(
				sale, "_require_access", return_value={"user": "sale@example.com", "profile": "sales"}
			),
			patch.object(sale, "_resolve_admission_year", return_value="2026"),
			patch.object(
				sale, "_resolve_sale_staff", return_value={"name": "STAFF-1", "user": "sale@example.com"}
			),
			patch.object(sale, "_now", return_value=as_of),
			patch.object(sale, "_viewer", return_value={"id": "sale@example.com", "displayName": "Sale"}),
			patch.object(sale, "_load_students", return_value=[]),
			patch.object(sale, "_load_interactions", return_value=[]),
			patch.object(sale, "_load_tasks", return_value=[]),
			patch.object(sale, "_load_leads", return_value=[]),
		):
			response = sale.get_sale_overview(admissionYear="2026", date="2026-09-05")

		self.assertEqual(
			set(response),
			{
				"meta",
				"tasks",
				"conversionTrend",
				"studentStages",
				"studentActions",
				"recentLeads",
				"recentStudents",
				"health",
			},
		)
		self.assertEqual(len(response["conversionTrend"]["ranges"]["4w"]["points"]), 4)
		self.assertEqual(len(response["conversionTrend"]["ranges"]["12w"]["points"]), 12)
		self.assertEqual(response["recentLeads"], [])
		self.assertEqual(response["recentStudents"], [])
		self.assertNotIn("slaBreach", response["health"])
