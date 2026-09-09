from datetime import datetime
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_dashboard


class TestDirectorDashboard(FrappeTestCase):
	def test_trend_range_validation_accepts_supported_values(self):
		for value in ("7d", "30d", "year", " YEAR "):
			with self.subTest(value=value):
				self.assertIn(
					director_dashboard._normalize_trend_range(value), director_dashboard.TREND_RANGES
				)

	def test_trend_range_validation_rejects_unknown_values(self):
		with self.assertRaises(frappe.ValidationError):
			director_dashboard._normalize_trend_range("14d")

	def test_pipeline_has_contract_order_and_calculates_biggest_drop(self):
		pipeline = director_dashboard._build_pipeline(
			{
				"prospect": 100,
				"engaged": 70,
				"qualified": 50,
				"counselling": 40,
				"application": 20,
				"accepted": 10,
				"enrolled": 5,
			}
		)

		self.assertEqual([stage["id"] for stage in pipeline["stages"]], list(director_dashboard.STAGE_ORDER))
		self.assertEqual(pipeline["stages"][1]["conversion"], "70,0%")
		self.assertEqual(pipeline["biggestDrop"]["fromStageId"], "prospect")
		self.assertEqual(pipeline["biggestDrop"]["toStageId"], "engaged")
		self.assertEqual(pipeline["summary"]["enrollmentRate"], 5.0)

	def test_application_statuses_are_projected_into_pipeline_stages(self):
		records = director_dashboard._build_student_records(
			[
				{"name": "STU-1", "processing_status": "processing"},
				{"name": "STU-2", "processing_status": "processed"},
			],
			[
				{"student": "STU-1", "status": "Accepted"},
				{"student": "STU-2", "status": "Enrolled"},
			],
		)

		self.assertIn("accepted", records[0]["stages"])
		self.assertIn("enrolled", records[1]["stages"])
		self.assertEqual(director_dashboard._stage_counts(records)["enrolled"], 1)

	def test_vietnamese_processing_status_is_normalized_before_stage_mapping(self):
		records = director_dashboard._build_student_records(
			[{"name": "STU-1", "processing_status": "Đã trúng tuyển"}], []
		)

		self.assertIn("accepted", records[0]["stages"])

	def test_interaction_evidence_keeps_engaged_distinct_from_qualified(self):
		records = director_dashboard._build_student_records(
			[{"name": "STU-1", "processing_status": "new"}],
			[],
			interactions=[{"student": "STU-1"}],
		)

		counts = director_dashboard._stage_counts(records)
		self.assertEqual(counts["engaged"], 1)
		self.assertEqual(counts["qualified"], 0)

	def test_target_scope_matches_canonical_planning_scope_keys(self):
		self.assertTrue(
			director_dashboard._target_matches_scope(
				{"planning_scope": "campus:HN", "scope_type": None, "scope": None},
				{"id": "HN", "label": "Hà Nội", "branch": "HN", "region": None},
			)
		)
		self.assertTrue(
			director_dashboard._target_matches_scope(
				{"planning_scope": "national", "scope_type": None, "scope": None},
				{"id": "all", "label": "Toàn bộ cơ sở", "branch": None, "region": None},
			)
		)
		self.assertFalse(
			director_dashboard._target_matches_scope(
				{"planning_scope": "campus:HN|major:CS", "scope_type": None, "scope": None},
				{"id": "HN", "label": "Hà Nội", "branch": "HN", "region": None},
			)
		)

	def test_year_trend_uses_requested_admission_year(self):
		as_of = datetime(2026, 8, 31, 10, 0, tzinfo=director_dashboard.LOCAL_TIMEZONE)
		trend = director_dashboard._build_trend(
			[
				{
					"stages": {"prospect"},
					"created_at": datetime(2025, 1, 15, tzinfo=director_dashboard.LOCAL_TIMEZONE),
				}
			],
			"year",
			as_of,
			2025,
		)

		self.assertEqual(len(trend["ranges"]["year"]["points"]), 12)
		self.assertEqual(trend["ranges"]["year"]["totals"]["newLeads"], 1)

	def test_territory_scope_filters_by_active_geography_assignment(self):
		students = [
			{"name": "STU-1", "province": "Hà Nội"},
			{"name": "STU-2", "province": "Hồ Chí Minh"},
		]
		scope = {
			"id": "territory-1",
			"label": "Miền Bắc",
			"branch": None,
			"region": "Miền Bắc",
			"territory": "territory-1",
			"territory_geographies": [{"geography_type": "Province", "geography": "Hà Nội"}],
		}

		filtered = director_dashboard._filter_students_by_scope(students, scope, {"provinces": {}})

		self.assertEqual([row["name"] for row in filtered], ["STU-1"])

	def test_kpi_change_is_unknown_without_historical_snapshot(self):
		kpis = director_dashboard._build_kpis(
			{stage: 0 for stage in director_dashboard.STAGE_ORDER},
			{},
		)

		self.assertTrue(all(kpi["change"] == "—" for kpi in kpis))

	def test_endpoint_returns_complete_guest_contract_without_identity_fields(self):
		as_of = datetime(2026, 8, 31, 10, 0, tzinfo=director_dashboard.LOCAL_TIMEZONE)
		students = [
			{
				"name": "STU-1",
				"processing_status": "NEW",
				"resolution": "PENDING",
				"creation": "2026-08-30 10:00:00",
				"province": "P-1",
				"source": "SRC-1",
			},
			{
				"name": "STU-2",
				"processing_status": "PROCESSED",
				"resolution": "PENDING",
				"creation": "2026-08-29 10:00:00",
				"province": "P-1",
				"source": "SRC-2",
			},
			{
				"name": "STU-3",
				"processing_status": "PROCESSED",
				"resolution": "CREATED",
				"creation": "2026-08-28 10:00:00",
				"enrollment_date": "2026-08-28",
				"province": "P-2",
				"source": "SRC-3",
			},
		]
		with (
			patch.object(director_dashboard, "_resolve_admission_year", return_value="2026"),
			patch.object(director_dashboard, "_now", return_value=as_of),
			patch.object(director_dashboard, "_load_students", return_value=students),
			patch.object(director_dashboard, "_load_applications", return_value=[]),
			patch.object(director_dashboard, "_load_lookups", return_value={"provinces": {}, "sources": {}}),
			patch.object(director_dashboard, "_load_targets", return_value={}),
			patch.object(director_dashboard, "_load_interactions", return_value=[]),
		):
			response = director_dashboard.get_director_overview(
				admissionYear="2026", scope="all", trendRange="30d"
			)

		self.assertEqual(
			set(response),
			{
				"meta",
				"kpis",
				"forecast",
				"briefing",
				"pipeline",
				"admissionsTrend",
				"marketOverview",
				"sourcePerformance",
				"weeklyActivity",
			},
		)
		self.assertEqual(len(response["kpis"]), 5)
		self.assertEqual(len(response["pipeline"]["stages"]), 7)
		self.assertEqual(len(response["marketOverview"]), 4)
		self.assertEqual(len(response["sourcePerformance"]), 5)
		self.assertEqual(len(response["weeklyActivity"]["points"]), 7)
		self.assertEqual(set(response["admissionsTrend"]["ranges"]), set(director_dashboard.TREND_RANGES))
		self.assertEqual(len(response["admissionsTrend"]["ranges"]["7d"]["points"]), 7)
		self.assertEqual(len(response["admissionsTrend"]["ranges"]["30d"]["points"]), 4)
		self.assertEqual(len(response["admissionsTrend"]["ranges"]["year"]["points"]), 8)
		self.assertEqual(response["meta"]["scopeLabel"], "Toàn bộ cơ sở")
		self.assertEqual(response["meta"]["asOf"], "2026-08-31T10:00:00+07:00")
		self.assertNotIn("STU-1", str(response))
