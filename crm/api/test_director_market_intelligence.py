"""Contract tests for the Director market projection."""

from __future__ import annotations

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api import director_market_intelligence as market


class TestDirectorMarketIntelligence(FrappeTestCase):
	def test_empty_scope_is_truthful_and_keeps_zero_counts(self):
		sources = {"provinces": [], "schools": [], "wards": [], "students": [], "snapshots": []}
		with patch.object(market, "require_director_access", return_value={}), patch.object(
			market, "resolve_admission_year", return_value="2026"
		), patch.object(market, "_load_sources", return_value=(sources, set())):
			response = market.get_director_market_intelligence_overview(
				admissionYear="2026", includeSchools="false", schoolLimit="1"
			)

		self.assertEqual(response["data"]["provinces"], [])
		self.assertEqual(response["data"]["totalSchools"], 0)
		self.assertIsNone(response["data"]["regionSummary"]["hotspotCount"])
		self.assertEqual(response["dataAvailability"]["fields"]["provinces[].opportunity"], "unavailable")

	def test_partial_snapshot_does_not_become_fake_opportunity(self):
		province = [{"name": "province-1", "province_code": "01", "province_name": "Hà Nội", "region": "Bắc"}]
		school = [{
			"name": "school-1", "school_name": "THPT Test", "school_code": "062", "province": "province-1",
			"ward": "ward-1", "school_area": None, "school_tier": None, "boarding_type": None,
			"latitude": None, "longitude": None, "address": None, "is_key_account": 0,
		}]
		sources = {"provinces": province, "schools": school, "wards": [{"name": "ward-1", "ward_code": "00123", "ward_name": "Phường Test"}], "students": [], "snapshots": []}
		with patch.object(market, "require_director_access", return_value={}), patch.object(
			market, "resolve_admission_year", return_value="2026"
		), patch.object(market, "_load_sources", return_value=(sources, {"snapshots"})):
			response = market.get_director_market_intelligence_overview(admissionYear=2026)

		item = response["data"]["provinces"][0]
		self.assertIsNone(item["opportunity"])
		self.assertIsNone(item["conversion"])
		self.assertEqual(item["leads"], 0)
		self.assertEqual(item["highSchools"][0]["id"], "01-00123-062")

	def test_student_source_failure_keeps_student_aggregates_unavailable(self):
		sources = {
			"provinces": [{"name": "province-1", "province_code": "01", "province_name": "Hà Nội", "region": "Bắc"}],
			"schools": [{"name": "school-1", "school_code": "062", "school_name": "THPT Test", "province": "province-1"}],
			"wards": [], "students": [], "snapshots": [],
		}
		response = market._build_overview(
			sources, {"students"}, admission_year="2026", region="all", metric="opportunity",
			include_schools=True, school_limit=6,
		)

		self.assertIsNone(response["data"]["provinces"][0]["leads"])
		self.assertIsNone(response["data"]["provinces"][0]["highSchools"][0]["prospects"])
		self.assertIsNone(response["data"]["regionSummary"]["totalLeads"])

	def test_query_contract_rejects_unknown_period(self):
		with patch.object(market, "require_director_access", return_value={}), patch.object(
			market, "resolve_admission_year", return_value="2026"
		):
			with self.assertRaises(market.frappe.ValidationError):
				market.get_director_market_intelligence_overview(period="7d")

	def test_empty_supporting_sources_are_partial_not_available(self):
		sources = {
			"provinces": [{"name": "province-1", "province_code": "01", "province_name": "Hà Nội", "region": "Bắc"}],
			"schools": [{"name": "school-1", "school_code": "062", "school_name": "THPT Test", "province": "province-1", "ward": "ward-1"}],
			"wards": [{"name": "ward-1", "ward_code": "00123", "ward_name": "Phường Test"}],
			"students": [], "snapshots": [],
		}
		with (
			patch.object(market, "require_director_access", return_value={}),
			patch.object(market, "resolve_admission_year", return_value="2026"),
			patch.object(market, "_load_sources", return_value=(sources, set())),
		):
			response = market.get_director_market_intelligence_overview(admissionYear="2026")

		self.assertEqual(response["status"], "partial")
		self.assertEqual(response["data"]["provinces"][0]["leads"], 0)
		self.assertEqual(response["dataAvailability"]["sections"]["students"], "available")
		self.assertEqual(response["dataAvailability"]["sections"]["snapshots"], "unavailable")

	def test_primary_source_failure_is_structured_503(self):
		response_state = {}
		with (
			patch.object(market, "require_director_access", return_value={}),
			patch.object(market, "resolve_admission_year", return_value="2026"),
			patch.object(market, "_load_sources", side_effect=market.MarketPrimarySourceUnavailable("schools")),
			patch.object(market.frappe.local, "response", response_state),
			self.assertRaises(market.frappe.ValidationError),
		):
			market.get_director_market_intelligence_overview(admissionYear="2026")

		self.assertEqual(response_state["http_status_code"], 503)
		self.assertEqual(response_state["error"]["code"], "MARKET_DATA_UNAVAILABLE")

	def test_latest_verified_snapshot_and_student_counts_are_deterministic(self):
		sources = {
			"provinces": [{"name": "province-1", "province_code": "01", "province_name": "Hà Nội", "region": "Bắc"}],
			"schools": [{"name": "school-1", "school_code": "062", "school_name": "THPT Test", "province": "province-1", "ward": "ward-1"}],
			"wards": [{"name": "ward-1", "ward_code": "00123", "ward_name": "Phường Test"}],
			"students": [
				{"name": "student-1", "high_school": "school-1", "province": "province-1"},
				{"name": "student-1", "high_school": "school-1", "province": "province-1"},
			],
			"snapshots": [
				{"name": "old", "high_school": "school-1", "verification_status": "Verified", "snapshot_date": "2026-01-01", "revision": 9, "applicant_count": 2},
				{"name": "new", "high_school": "school-1", "verification_status": "Verified", "snapshot_date": "2026-08-01", "revision": 1, "applicant_count": 7},
				{"name": "rejected", "high_school": "school-1", "verification_status": "Rejected", "snapshot_date": "2026-12-01", "revision": 99, "applicant_count": 99},
			],
		}
		response = market._build_overview(
			sources, set(), admission_year="2026", region="all", metric="opportunity",
			include_schools=True, school_limit=6,
		)

		province = response["data"]["provinces"][0]
		self.assertEqual(province["leads"], 1)
		self.assertEqual(province["highSchools"][0]["prospects"], 1)
		self.assertEqual(province["highSchools"][0]["applications"], 7)

	def test_method_has_no_guest_or_permission_bypass(self):
		source = market.__loader__.get_source(market.__name__)
		self.assertNotIn("allow_guest=True", source)
		self.assertNotIn("get_all(", source)
		self.assertNotIn("ignore_permissions", source)

	def test_unexpected_primary_defect_is_not_disguised_as_503(self):
		with (
			patch.object(market, "require_director_access", return_value={}),
			patch.object(market, "resolve_admission_year", return_value="2026"),
			patch.object(market, "_load_sources", side_effect=RuntimeError("programming defect")),
			self.assertRaisesRegex(RuntimeError, "programming defect"),
		):
			market.get_director_market_intelligence_overview(admissionYear="2026")
