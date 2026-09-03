from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_school_field_activity as activity


class TestDirectorSchoolFieldActivity(FrappeTestCase):
	def test_query_parsers_are_strict(self):
		self.assertEqual(activity._parse_admission_year(" 2026 "), "2026")
		self.assertEqual(activity._parse_period("6m"), "6m")
		self.assertEqual(activity._parse_limit("200", field="activityLimit", minimum=1, maximum=200, default=50), 200)
		self.assertEqual(
			activity._parse_limit(
				None,
				field="activityLimit",
				minimum=1,
				maximum=200,
				default=activity.ACTIVITY_LIMIT_DEFAULT,
			),
			5,
		)
		self.assertEqual(
			activity._parse_limit(
				None,
				field="upcomingLimit",
				minimum=1,
				maximum=50,
				default=activity.UPCOMING_LIMIT_DEFAULT,
			),
			5,
		)
		self.assertEqual(activity._parse_boolean("false", default=True), False)

		for value in ("1999", "2101", "26", "202.6"):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				activity._parse_admission_year(value)
		for value in ("week",):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				activity._parse_period(value)
		with self.assertRaises(frappe.ValidationError):
			activity._parse_limit("201", field="activityLimit", minimum=1, maximum=200, default=50)
		with self.assertRaises(frappe.ValidationError):
			activity._parse_boolean("yes", default=True)

	def test_completed_activity_uses_canonical_attribution_and_nulls_unavailable_cost(self):
		row = {
			"name": "ACT-1",
			"high_school": "SCHOOL-1",
			"title": "Ngày hội hướng nghiệp",
			"activity_type": "career-talk",
			"activity_date": "2026-05-28",
			"scheduled_datetime": "2026-05-28 08:00:00",
			"owner_staff": "STAFF-1",
			"status": "Completed",
			"prospect_count": 999,
		}
		attribution = {
			"ACT-1": {
				"students": {"STU-1", "STU-2"},
				"verified": {"STU-1"},
				"qualified": {"STU-1", "STU-2"},
				"enrolled": {"STU-2"},
				"quality": "verified",
			}
		}
		item = activity._build_completed_activity(
			row,
			attribution=attribution,
			schools={"SCHOOL-1": {"school_name": "THPT Test", "province": "province-1"}},
			staff={"STAFF-1": {"full_name": "Người phụ trách"}},
			activity_types={"career-talk": "Career Talk"},
		)

		self.assertEqual(item["leads"], 2)
		self.assertEqual(item["verifiedLeads"], 1)
		self.assertEqual(item["verifiedRate"], 50.0)
		self.assertEqual(item["qualified"], 2)
		self.assertEqual(item["enrolled"], 1)
		self.assertEqual(item["dataQuality"], "verified")
		self.assertEqual(item["cost"], {"amount": None, "unit": "vnd"})
		self.assertEqual(item["costPerEnrollment"], {"amount": None, "unit": "vnd"})
		self.assertEqual(item["owner"], "Người phụ trách")
		self.assertEqual(item["location"], "province-1")

	def test_reported_activity_leads_are_partial_and_do_not_become_enrollments(self):
		row = {
			"name": "ACT-2",
			"high_school": "SCHOOL-1",
			"activity_type": "career-talk",
			"activity_date": "2026-05-28",
			"status": "Completed",
			"prospect_count": 12,
			"contact_count": 8,
			"application_count": 3,
		}
		item = activity._build_completed_activity(
			row,
			attribution={},
			schools={"SCHOOL-1": {"school_name": "THPT Test", "province": "province-1"}},
			staff={},
			activity_types={"career-talk": "Career Talk"},
		)

		self.assertEqual(item["leads"], 12)
		self.assertIsNone(item["verifiedLeads"])
		self.assertIsNone(item["qualified"])
		self.assertIsNone(item["enrolled"])
		self.assertEqual(item["dataQuality"], "partial")

	def test_completed_activity_selection_uses_only_proven_cost_per_enrollment(self):
		activities = [
			{"id": "ACT-1", "costPerEnrollment": {"amount": None, "unit": "million_vnd"}},
			{"id": "ACT-2", "costPerEnrollment": {"amount": 3, "unit": "million_vnd"}},
			{"id": "ACT-3", "costPerEnrollment": {"amount": 0, "unit": "million_vnd"}},
			{"id": "ACT-4", "costPerEnrollment": {"amount": 5, "unit": "million_vnd"}},
		]

		selected = activity._select_completed_activities_for_cost_chart(activities, limit=2)

		self.assertEqual([item["id"] for item in selected], ["ACT-2", "ACT-3"])

	def test_upcoming_activity_exposes_seeded_forecast_fields(self):
		item = activity._build_upcoming_activity(
			{
				"name": "ACT-PLAN-1",
				"high_school": "SCHOOL-1",
				"activity_type": "career-talk",
				"scheduled_datetime": "2026-09-07 08:00:00",
				"status": "Planned",
				"expected_enrollment_min": 9,
				"expected_enrollment_max": 14,
				"forecast_confidence": 71,
				"forecast_sample_size": 4,
				"forecast_source": "historical-activity",
				"evidence_reference": "demo:historical-school-activity",
			},
			schools={"SCHOOL-1": {"school_name": "THPT Test", "province": "province-1"}},
			activity_types={"career-talk": "Career Talk"},
		)

		self.assertEqual(item["expectedEnrollment"], {"min": 9, "max": 14, "unit": "students"})
		self.assertEqual(item["confidence"], 71.0)
		self.assertEqual(item["historicalSampleSize"], 4)
		self.assertEqual(item["source"], "historical-activity")
		self.assertEqual(item["evidence"], ["demo:historical-school-activity"])

	def test_kpis_use_all_completed_rows_and_null_unavailable_denominators(self):
		rows = [
			{"leads": 10, "enrolled": 2, "cost": {"amount": 20, "unit": "million_vnd"}},
			{"leads": 5, "enrolled": None, "cost": {"amount": 0, "unit": "million_vnd"}},
		]
		kpis = {row["id"]: row for row in activity._build_kpis(rows, total_prospects=None, unsynced=None)}

		self.assertEqual(kpis["activity-count"]["value"], 2)
		self.assertEqual(kpis["field-leads"]["value"], 15)
		self.assertIsNone(kpis["field-leads"]["shareOfProspects"])
		self.assertEqual(kpis["cost-per-enrollment"]["value"], 10.0)
		self.assertEqual(kpis["field-conversion"]["value"], round(2 / 15 * 100, 1))
		self.assertIsNone(kpis["unsynced-records"]["value"])

	def test_data_quality_uses_aggregate_phone_and_consent_signals(self):
		quality = activity._build_data_quality(
			[
				{"id": "ACT-1", "ownerId": "STAFF-1", "leads": 2},
			],
			{"STAFF-1": {"full_name": "Người phụ trách"}},
			attribution={
				"ACT-1": {
					"students": {"STU-1", "STU-2"},
					"phone_reachable": {"STU-1"},
					"consent": {"STU-1"},
				}
			},
		)

		metrics = {metric["id"]: metric for metric in quality["seasonMetrics"]}
		self.assertEqual(metrics["reachable-phone"]["value"], 50.0)
		self.assertEqual(metrics["reachable-phone"]["status"], "below_target")
		self.assertEqual(metrics["data-consent"]["value"], 50.0)
		self.assertEqual(metrics["data-consent"]["status"], "below_target")
		self.assertIsNone(metrics["receipt-image"]["value"])

	def test_endpoint_returns_contract_shape_and_allows_guest_aggregate(self):
		as_of = datetime(2026, 8, 31, 10, 0, tzinfo=activity.LOCAL_TIMEZONE)
		with (
			patch.object(activity, "_request_access", return_value={"roleState": "canonical_profile"}),
			patch.object(activity, "_resolve_admission_year", return_value="2026"),
			patch.object(activity, "_normalize_scope", return_value={"id": "all", "label": "Toàn bộ cơ sở", "kind": "all"}),
			patch.object(activity, "_now", return_value=as_of),
			patch.object(activity, "_load_admission_year_config", return_value={}),
			patch.object(activity, "_load_activity_rows", return_value=([], "available", "available")),
			patch.object(activity, "_load_attribution", return_value=({}, "unavailable")),
			patch.object(activity, "_load_lookups", return_value=({}, {}, {})),
			patch.object(activity, "_load_device_sync", return_value=(None, "unavailable")),
		):
			response = activity.get_director_school_field_activity(admissionYear="2026")

		self.assertEqual(
			set(response),
			{"meta", "kpis", "completedActivities", "upcomingActivities", "dataQuality", "deviceSync"},
		)
		self.assertEqual(response["meta"]["admissionYear"], 2026)
		self.assertEqual(response["meta"]["period"], "season")
		self.assertEqual(response["meta"]["asOf"], "2026-08-31T10:00:00+07:00")
		self.assertEqual(response["meta"]["status"], "partial")
		self.assertIsNone(response["deviceSync"])

		source = activity.__loader__.get_source(activity.__name__)
		self.assertIn('@frappe.whitelist(allow_guest=True, methods=["GET"])', source)
		self.assertIn("allow_guest=True", source)
		self.assertIn("require_director_access()", source)

	def test_guest_scope_is_limited_to_unscoped_aggregate(self):
		with patch.object(activity.frappe, "session", SimpleNamespace(user="Guest")):
			access = activity._request_access()

		self.assertEqual(access, {"user": "Guest", "roleState": "guest"})
		activity._authorize_scope({"kind": "all"}, access)
		with self.assertRaises(frappe.PermissionError):
			activity._authorize_scope({"kind": "campus", "value": "campus-1"}, access)

	def test_scope_resolver_supports_province_code(self):
		with patch.object(
			activity,
			"_fetch_rows",
			side_effect=[
				[],
				[],
				[],
				[],
				[{"name": "province-1", "province_name": "Hà Nội", "province_code": "01"}],
			],
		):
			scope = activity._normalize_scope("01")

		self.assertEqual(scope["id"], "province-1")
		self.assertEqual(scope["kind"], "province")
		self.assertEqual(scope["label"], "Hà Nội")
