from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_demographics


class TestDirectorDemographics(FrappeTestCase):
	def test_period_normalization_accepts_supported_values(self):
		self.assertEqual(director_demographics._normalize_period("6m"), "6m")
		self.assertEqual(director_demographics._normalize_period("12M"), "12m")
		self.assertEqual(director_demographics._normalize_period("season"), "season")

	def test_period_normalization_rejects_unknown_values(self):
		with self.assertRaises(frappe.ValidationError):
			director_demographics._normalize_period("3m")

	def test_empty_overview_keeps_contract_shape(self):
		with (
			patch.object(director_demographics, "_resolve_admission_year", return_value="2026"),
			patch.object(director_demographics, "_load_students", return_value=[]),
		):
			response = director_demographics.get_director_demographics_overview(
				admissionYear="2026", period="6m", scope="all"
			)

		self.assertEqual(
			set(response),
			{"data", "meta"},
		)
		self.assertEqual(
			set(response["data"]),
			{
				"kpis",
				"demand",
				"acquisitionMap",
				"audienceComposition",
				"segments",
				"regionOpportunities",
				"regionalDemand",
				"dataCoverage",
			},
		)
		self.assertEqual(response["meta"]["admissionYear"], 2026)
		self.assertEqual(response["meta"]["minSampleSize"], 30)
		self.assertEqual(response["data"]["segments"], [])
		self.assertEqual(
			set(response["data"]["acquisitionMap"]),
			{
				"attributionModel",
				"platformLeadCost",
				"leadTrendComparison",
				"dailySpendLeads",
				"touchpointPlatformMatrix",
				"budgetByPlatformRole",
				"formFunnel",
				"formCompletion",
				"formDropoffByField",
				"captureModeComparison",
				"leadQualityBySource",
				"validLeadRateTrend",
				"handoffDataCompleteness",
				"identityMatchBreakdown",
				"firstTouchBySource",
				"lastTouchBySource",
				"firstVsLastSource",
				"attributionFlow",
				"cohortEnrollmentMatrix",
				"enrollmentLagHistogram",
				"cumulativeConversion",
				"firstContactLatency",
				"submissionTiming",
				"handoffSuccessBySource",
				"costPerEnrolledBySource",
			},
		)
		self.assertEqual(
			response["data"]["acquisitionMap"]["enrollmentLagHistogram"], {"medianDays": None, "buckets": []}
		)
		self.assertEqual(response["meta"]["dataAvailability"]["acquisitionMap"], "unavailable")
		self.assertEqual(
			{
				key: response["meta"][key]
				for key in ("page", "pageSize", "total", "totalPages", "hasNextPage")
			},
			{"page": 1, "pageSize": 5, "total": 0, "totalPages": 1, "hasNextPage": False},
		)

	def test_pagination_slices_sorted_segments_after_counting_total(self):
		segments = [{"id": f"segment-{index}"} for index in range(7)]

		page, meta = director_demographics._paginate_segments(segments, page=2, page_size=3)

		self.assertEqual([segment["id"] for segment in page], ["segment-3", "segment-4", "segment-5"])
		self.assertEqual(meta, {"page": 2, "pageSize": 3, "total": 7, "totalPages": 3, "hasNextPage": True})

	def test_overview_applies_pagination_to_sorted_segments(self):
		segments = [{"id": f"segment-{index}"} for index in range(7)]
		with (
			patch.object(director_demographics, "_resolve_admission_year", return_value="2026"),
			patch.object(director_demographics, "_load_students", return_value=[]),
			patch.object(director_demographics, "_build_segments", return_value=segments),
		):
			response = director_demographics.get_director_demographics_overview(
				admissionYear="2026", page="2", pageSize="3"
			)

		self.assertEqual(
			[segment["id"] for segment in response["data"]["segments"]],
			["segment-3", "segment-4", "segment-5"],
		)
		self.assertEqual(
			{
				key: response["meta"][key]
				for key in ("page", "pageSize", "total", "totalPages", "hasNextPage")
			},
			{"page": 2, "pageSize": 3, "total": 7, "totalPages": 3, "hasNextPage": True},
		)

	def test_pagination_rejects_invalid_page_and_page_size(self):
		with self.assertRaises(frappe.ValidationError):
			director_demographics._normalize_pagination("0", "5")
		with self.assertRaises(frappe.ValidationError):
			director_demographics._normalize_pagination("1", "101")
		with self.assertRaises(frappe.ValidationError):
			director_demographics._normalize_pagination("9" * 5000, "5")
		with self.assertRaises(frappe.ValidationError):
			director_demographics._paginate_segments([], page=2, page_size=5)

	def test_interest_bucket_uses_major_group_keywords(self):
		bucket = director_demographics._interest_bucket("", "Kỹ thuật phần mềm", "")

		self.assertEqual(bucket, {"id": "software", "label": "Phần mềm"})

	def test_audience_composition_includes_public_school_profile(self):
		composition = director_demographics._build_audience_composition(
			[
				{
					"gender_label": "Nữ",
					"grade_id": "grade-12",
					"has_interest": True,
					"school_type": "Công lập",
				},
			]
		)

		profile_ids = {profile["id"] for profile in composition["profiles"]}
		self.assertIn("public-school", profile_ids)

	def test_segment_projection_does_not_include_personal_identity(self):
		record = director_demographics._enrich_student(
			frappe._dict(
				name="ENR-1",
				student_name="Nguyễn Minh An",
				gender="Nữ",
				current_grade="12",
				major="M-1",
				province="P-1",
				creation="2026-08-01 10:00:00",
			),
			lookups={
				"majors": {"M-1": {"label": "Trí tuệ nhân tạo", "group": "AI"}},
				"provinces": {"P-1": {"label": "Cần Thơ", "region": "Mekong"}},
				"regions": {"Mekong": "Đồng bằng sông Cửu Long"},
				"schools": {},
			},
			evidence={"interactions": [], "assessment": {}, "applications": []},
		)

		self.assertEqual(record["interest"], {"id": "ai", "label": "AI"})
		self.assertNotIn("student_name", record)
		self.assertNotIn("phone", record)
		self.assertNotIn("email", record)
