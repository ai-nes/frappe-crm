from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import sale


class TestSaleOverview(FrappeTestCase):
	def test_pipeline_and_status_are_built_from_one_scoped_student_set(self):
		students = [
			{"name": "STU-1", "student_name": "Một", "processing_status": "PROCESSING", "resolution": "PENDING"},
			{"name": "STU-2", "student_name": "Hai", "processing_status": "PROCESSED", "resolution": "PENDING"},
			{"name": "STU-3", "student_name": "Ba", "processing_status": "PROCESSED", "resolution": "CREATED"},
		]
		contacts = [
			{"student": "STU-1", "quality_bucket": "High Intent"},
			{"student": "STU-2", "readiness_level": "Level 3"},
		]
		applications = [
			{
				"student": "STU-2",
				"status": "Under Review",
				"document_total": 3,
				"document_completed": 2,
			},
			{"student": "STU-3", "status": "Enrolled", "enrolled_at": "2026-09-01 10:00:00"},
		]
		interactions = [
			{
				"student": "STU-1",
				"interaction_type": "Counseling",
				"interaction_datetime": "2026-09-01 10:00:00",
				"outcome": "qualified",
			},
		]

		records = sale._build_student_records(students, contacts, applications, interactions)
		pipeline = sale._build_pipeline(records)
		kpis = {item["id"]: item["value"] for item in sale._build_kpis(records)}
		status = sale._build_student_status(records)

		self.assertEqual([item["count"] for item in pipeline["stages"]], [3, 1, 1, 1, 1, 1, 1])
		self.assertEqual(
			kpis, {"assigned": 3, "consulting": 1, "qualified": 2, "documents": 1, "admission": 1}
		)
		self.assertEqual(sum(item["count"] for item in status["items"]), status["total"])
		self.assertEqual(status["total"], kpis["assigned"])

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
					"objective": "Nhắc học bạ",
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

	def test_endpoint_returns_the_complete_contract_and_does_not_query_unscoped_students(self):
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
			patch.object(sale, "_load_contacts", return_value=[]),
			patch.object(sale, "_load_applications", return_value=[]),
			patch.object(sale, "_load_interactions", return_value=[]),
			patch.object(sale, "_load_tasks", return_value=[]),
		):
			response = sale.get_sale_overview(admissionYear="2026", date="2026-09-05")

		self.assertEqual(
			set(response),
			{
				"meta",
				"kpis",
				"tasks",
				"pipeline",
				"attention",
				"conversionTrend",
				"studentStatus",
				"operations",
			},
		)
		self.assertEqual(len(response["kpis"]), 5)
		self.assertEqual(len(response["pipeline"]["stages"]), 7)
		self.assertEqual(len(response["conversionTrend"]["ranges"]["4w"]["points"]), 4)
		self.assertEqual(len(response["conversionTrend"]["ranges"]["12w"]["points"]), 12)
		self.assertEqual(response["studentStatus"]["total"], 0)
