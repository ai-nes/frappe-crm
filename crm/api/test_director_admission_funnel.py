from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_admission_funnel
from crm.demo import seed_admission_funnel


class TestDirectorAdmissionFunnel(FrappeTestCase):
	def test_admission_year_validation_is_four_digits_in_supported_range(self):
		self.assertEqual(director_admission_funnel._parse_admission_year(" 2026 "), "2026")

		for value in ("1999", "2101", "202.6", "26", "20260"):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				director_admission_funnel._parse_admission_year(value)

	def test_funnel_builders_keep_contract_order_and_null_zero_denominators(self):
		records = [
			{"stages": {"prospect", "engaged", "qualified", "application"}},
			{"stages": {"prospect", "engaged"}},
		]

		stages = director_admission_funnel._build_stages(records)
		self.assertEqual([item["id"] for item in stages], list(director_admission_funnel.STAGE_ORDER))
		self.assertEqual([item["count"] for item in stages], [2, 2, 1, 1, 1, 0, 0])
		self.assertEqual(stages[0]["stepRate"], 100.0)
		self.assertEqual(stages[1]["stepRate"], 100.0)
		self.assertIsNone(stages[-1]["stepRate"])

		drop_offs = director_admission_funnel._build_drop_offs(stages)
		self.assertEqual(len(drop_offs), 6)
		self.assertEqual(drop_offs[0]["fromStageId"], "application")
		self.assertEqual(drop_offs[0]["toStageId"], "accepted")
		self.assertEqual(drop_offs[0]["dropCount"], 1)
		self.assertEqual(drop_offs[0]["dropRate"], 100.0)

		summary = director_admission_funnel._build_summary(records, stages, drop_offs)
		self.assertEqual(summary["prospects"], 2)
		self.assertEqual(summary["enrollmentRate"], 0.0)
		self.assertEqual(summary["priorityStageId"], "application")
		self.assertEqual(summary["priorityNextStageId"], "accepted")

	def test_aging_uses_mutually_exclusive_buckets_and_median(self):
		as_of = datetime(2026, 8, 31, 10, 0, tzinfo=director_admission_funnel.LOCAL_TIMEZONE)
		records = [
			{
				"activeStage": "prospect",
				"stageEnteredAt": {"prospect": "2026-08-31 09:00:00+07:00"},
			},
			{
				"activeStage": "prospect",
				"stageEnteredAt": {"prospect": "2026-08-27 09:00:00+07:00"},
			},
			{
				"activeStage": "prospect",
				"stageEnteredAt": {"prospect": "2026-08-01 09:00:00+07:00"},
			},
		]

		aging = director_admission_funnel._build_aging(records, as_of)
		row = aging["rows"][0]
		self.assertEqual(
			(
				row["underThreeDays"],
				row["threeToSevenDays"],
				row["sevenToFourteenDays"],
				row["overFourteenDays"],
			),
			(1, 1, 0, 1),
		)
		self.assertEqual(row["medianDays"], 4.0)
		self.assertEqual(aging["totalOverFourteenDays"], 1)

	def test_cohort_marks_unobserved_horizon_as_null(self):
		as_of = datetime(2026, 8, 31, 10, 0, tzinfo=director_admission_funnel.LOCAL_TIMEZONE)
		records = [
			{
				"id": "STU-1",
				"createdAt": "2026-01-01 10:00:00+07:00",
				"stageEnteredAt": {"application": "2026-08-08 10:00:00+07:00"},
			},
			{
				"id": "STU-2",
				"createdAt": "2026-08-24 10:00:00+07:00",
			},
		]

		cohorts = director_admission_funnel._build_cohorts(records, as_of)
		self.assertEqual(cohorts["targetStageId"], "application")
		self.assertEqual(cohorts["followUpWeeks"], [1, 2, 3, 4, 5, 6])
		self.assertEqual(cohorts["completeCohortCount"], 1)
		self.assertTrue(any(value is None for row in cohorts["rows"] for value in row["values"]))

	def test_seeded_historical_cohorts_have_a_complete_line(self):
		as_of = datetime(2026, 8, 31, 10, 0, tzinfo=director_admission_funnel.LOCAL_TIMEZONE)
		records = [
			{
				"id": f"seed-{index}",
				"createdAt": seed_admission_funnel.snapshot_datetime(as_of, index).isoformat(),
				"applicantAt": (
					seed_admission_funnel.snapshot_datetime(as_of, index) + timedelta(days=2)
				).isoformat(),
			}
			for index in range(seed_admission_funnel.SNAPSHOT_STUDENT_COUNT)
		]
		records.append({"id": "seed-current", "createdAt": as_of.isoformat()})

		cohorts = director_admission_funnel._build_cohorts(records, as_of)

		self.assertGreater(cohorts["completeCohortCount"], 0)
		self.assertTrue(any(all(value is not None for value in row["values"]) for row in cohorts["rows"]))

	def test_source_performance_keeps_only_the_ten_largest_sources(self):
		records = [
			{"sourceId": f"source-{index:02d}", "stages": {"prospect"}}
			for index in range(12)
			for _ in range(12 - index)
		]
		source_rows = [
			{"name": f"source-{index:02d}", "source_name": f"Nguồn {index:02d}"} for index in range(12)
		]

		performance = director_admission_funnel._build_source_performance(records, source_rows)

		self.assertEqual(len(performance), 10)
		self.assertEqual([item["id"] for item in performance], [f"source-{index:02d}" for index in range(10)])

	def test_endpoint_returns_documented_snapshot_shape_and_guest_whitelist(self):
		as_of = datetime(2026, 8, 31, 10, 0, tzinfo=director_admission_funnel.LOCAL_TIMEZONE)
		with (
			patch.object(director_admission_funnel, "_resolve_admission_year", return_value="2026"),
			patch.object(
				director_admission_funnel,
				"_normalize_scope",
				return_value={"id": "all", "label": "Toàn bộ cơ sở", "branch": None, "territory": None},
			),
			patch.object(director_admission_funnel, "_authorize_scope"),
			patch.object(director_admission_funnel, "_now", return_value=as_of),
			patch.object(director_admission_funnel, "_load_snapshot_records", return_value=[]),
			patch.object(director_admission_funnel, "_load_sources", return_value=[]),
		):
			response = director_admission_funnel.get_director_admission_funnel(
				admissionYear="2026", scope="all"
			)

		self.assertEqual(
			set(response),
			{
				"meta",
				"summary",
				"stages",
				"dropOffs",
				"aging",
				"sourcePerformance",
				"cohorts",
				"priorityActions",
			},
		)
		self.assertEqual(len(response["stages"]), 7)
		self.assertEqual(len(response["dropOffs"]), 6)
		self.assertEqual(len(response["aging"]["rows"]), 6)
		self.assertEqual(response["meta"]["status"], "available")
		self.assertEqual(response["meta"]["asOf"], "2026-08-31T10:00:00+07:00")
		self.assertTrue(
			getattr(director_admission_funnel.get_director_admission_funnel, "is_whitelisted", False)
			or director_admission_funnel.get_director_admission_funnel
			in getattr(frappe, "guest_methods", set())
		)
