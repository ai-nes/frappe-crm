from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_campaign_intelligence


class TestDirectorCampaignIntelligence(FrappeTestCase):
	def test_build_response_preserves_campaign_summary_and_funnel_contract(self):
		facts = [
			{
				"campaign": "CAM-1",
				"channel": "Facebook",
				"period_start": "2026-08-03",
				"spend": 100,
				"impressions": 1000,
				"clicks": 100,
				"leads": 20,
				"applications": 8,
				"enrolled": 2,
				"raw_measures": {"landing_visits": 70, "qualified_leads": 12, "confirmed_revenue": 250},
			},
			{
				"campaign": "CAM-2",
				"channel": "Google",
				"period_start": "2026-08-10",
				"spend": 50,
				"impressions": 500,
				"clicks": 60,
				"leads": 10,
				"applications": 4,
				"enrolled": 1,
				"raw_measures": {"landing_visits": 50, "qualified_leads": 5, "confirmed_revenue": 75},
			},
		]

		response = director_campaign_intelligence._build_response(
			"2026",
			date(2026, 8, 1),
			date(2026, 8, 31),
			"week",
			{"id": "all"},
			facts,
			{"CAM-1": {"title": "Open Day"}, "CAM-2": {"title": "Search"}},
			{"CAM-1": 90, "CAM-2": 55},
			[],
		)

		self.assertEqual(
			response["summary"],
			{
				"spend": 150.0,
				"qualifiedLeads": 17,
				"applications": 12,
				"enrollments": 3,
				"confirmedRevenue": 325.0,
				"roas": 2.17,
			},
		)
		self.assertEqual(
			[row["id"] for row in response["funnel"]],
			[stage[0] for stage in director_campaign_intelligence.FUNNEL_STAGES],
		)
		self.assertEqual(response["funnel"][0]["rate"], 100.0)
		self.assertEqual(response["campaigns"][0]["name"], "Open Day")
		self.assertEqual(response["campaigns"][0]["attributionConfidence"], "high")
		self.assertEqual(response["meta"]["status"], "available")

	def test_date_range_rejects_inverted_dates(self):
		with self.assertRaises(frappe.ValidationError):
			director_campaign_intelligence._resolve_date_range("2026", "2026-09-01", "2026-08-31")

	def test_endpoint_returns_documented_shape(self):
		with (
			patch.object(
				director_campaign_intelligence,
				"require_campaign_intelligence_access",
				return_value={"user": "director@example.com", "roleState": "canonical_profile"},
			),
			patch.object(director_campaign_intelligence, "resolve_admission_year", return_value="2026"),
			patch.object(
				director_campaign_intelligence,
				"_resolve_date_range",
				return_value=(date(2026, 1, 1), date(2026, 12, 31), []),
			),
			patch.object(
				director_campaign_intelligence,
				"_resolve_scope",
				return_value={"id": "all", "territory": None},
			),
			patch.object(director_campaign_intelligence, "_resolve_link_filter", return_value=None),
			patch.object(director_campaign_intelligence, "_load_facts", return_value=[]),
			patch.object(director_campaign_intelligence, "_load_campaigns", return_value={}),
			patch.object(director_campaign_intelligence, "_load_attribution", return_value={}),
			patch.object(director_campaign_intelligence, "_load_campaign_lead_rows", return_value={}),
		):
			response = director_campaign_intelligence.get_director_campaign_intelligence("2026")

		self.assertEqual(
			set(response),
			{"meta", "generatedAt", "summary", "trend", "funnel", "campaigns", "recommendation"},
		)
		self.assertEqual(response["summary"]["spend"], 0.0)
		self.assertEqual(len(response["funnel"]), 7)

	def test_primary_attribution_is_stable_and_deduplicates_across_campaigns(self):
		rows = [
			{"name": "ATT-2", "student": "STU-1", "campaign": "CAM-2", "weight": 1, "confidence": 100},
			{"name": "ATT-1", "student": "STU-1", "campaign": "CAM-1", "is_first_touch": 1, "weight": 0.1},
			{"name": "ATT-3", "student": "STU-2", "campaign": "CAM-2", "weight": 0.8, "confidence": 50},
			{"name": "ATT-4", "student": "STU-2", "campaign": "CAM-1", "weight": 0.5, "confidence": 90},
		]
		primary = director_campaign_intelligence._primary_attributions(rows)
		self.assertEqual(primary["STU-1"]["campaign"], "CAM-1")
		self.assertEqual(primary["STU-2"]["campaign"], "CAM-2")
		self.assertEqual(primary, director_campaign_intelligence._primary_attributions(list(reversed(rows))))

	def test_primary_attribution_uses_confidence_time_then_id_for_ties(self):
		base = {"student": "STU-1", "campaign": "CAM-1", "weight": 1, "confidence": 80}
		rows = [
			{**base, "name": "ATT-1", "confidence": 50, "attributed_at": "2026-01-01"},
			{**base, "name": "ATT-2", "attributed_at": "2026-02-02"},
			{**base, "name": "ATT-4", "attributed_at": "2026-02-01"},
			{**base, "name": "ATT-3", "attributed_at": "2026-02-01"},
		]
		self.assertEqual(director_campaign_intelligence._primary_attributions(rows)["STU-1"]["name"], "ATT-3")

	def test_canonical_processing_and_resolution_groups_keep_quality_separate(self):
		cases = [
			({"processing_status": "NEW", "resolution": "PENDING"}, "new"),
			({"processing_status": "PROCESSING", "resolution": "PENDING"}, "in_progress"),
			({"processing_status": "PROCESSED", "resolution": "PENDING"}, "in_progress"),
			({"processing_status": "CLOSED", "resolution": "INVALID"}, "disqualified"),
			({"processing_status": "CLOSED", "resolution": "DUPLICATE"}, "duplicate"),
			({"processing_status": "PROCESSED", "resolution": "CREATED"}, "converted"),
		]
		for status, expected in cases:
			with self.subTest(status=status):
				self.assertEqual(
					director_campaign_intelligence._lead_status_group(
						status["processing_status"], status
					),
					expected,
				)
		self.assertEqual(director_campaign_intelligence._lead_status_group("UNMAPPED", {}), "unknown")

	def test_counts_reconcile_quality_and_include_attribution_only_campaign(self):
		leads = {"CAM-1": [{"statusGroup": "new"}, {"statusGroup": "converted"}, {"statusGroup": "duplicate"}]}
		campaigns = director_campaign_intelligence._build_campaigns(
			[{"campaign": "EMPTY"}], {"CAM-1": {"title": "Lead only"}}, {}, leads)
		row = next(row for row in campaigns if row["id"] == "CAM-1")
		self.assertEqual(row["leadCount"], 3)
		self.assertEqual(row["qualityCount"], 1)
		self.assertEqual(sum(item["count"] for item in row["statusBreakdown"]) + row["qualityCount"], 3)
		self.assertEqual(row["statusBreakdown"][0]["share"], 33.3)
		empty = next(row for row in campaigns if row["id"] == "EMPTY")
		self.assertEqual(empty["leadCount"], 0)
		self.assertTrue(all(item["share"] == 0 for item in empty["statusBreakdown"]))

	def test_missing_lead_source_is_distinct_from_zero_leads(self):
		campaigns = director_campaign_intelligence._build_campaigns(
			[{"campaign": "C1"}], {"C1": {"title": "Campaign"}}, {}, None
		)
		self.assertIsNone(campaigns[0]["leadCount"])
		self.assertIsNone(campaigns[0]["statusBreakdown"])
		self.assertIsNone(campaigns[0]["qualityCount"])

	def test_cohort_filters_students_with_permissions_and_primary_before_campaign_filter(self):
		api = director_campaign_intelligence
		attributions = [
			{"name": "A", "student": "S1", "campaign": "C1", "is_first_touch": 1},
			{"name": "B", "student": "S1", "campaign": "C2"},
			{"name": "C", "student": "S2", "campaign": "C2"},
		]
		def get_all(doctype, **kwargs):
			return {"CRM Campaign Attribution": attributions,
				"CRM Campaign Channel Assignment": [{"campaign": "C2"}], "CRM Team": ["TEAM-1"],
				"CRM Enrollment Status": [{"name": "NEW", "display_name": "Mới"}]}[doctype]
		with patch.object(frappe.db, "table_exists", return_value=True), \
			patch.object(frappe, "get_all", side_effect=get_all) as all_query, \
			patch.object(frappe, "get_list", side_effect=[[{"name": "C2"}],
				[{"name": "S2", "lead_code": "LD-2026-00002", "processing_status": "NEW", "resolution": "PENDING"}]]) as visible_query, \
			patch.object(frappe.db, "get_value", return_value="YEAR-2026"):
			result = api._load_campaign_lead_rows("2026", date(2026, 8, 1), date(2026, 8, 31),
				"CAMPUS-1", "CHANNEL-1", {"territory": "T1"})
		self.assertEqual([row["name"] for row in result["C2"]], ["S2"])
		filters = visible_query.call_args_list[1].kwargs["filters"]
		self.assertEqual(filters, {"name": ["in", ["S2"]], "admission_year": "YEAR-2026",
			"branch": "CAMPUS-1", "owning_team": ["in", ["TEAM-1"]]})
		self.assertEqual(all_query.call_args_list[1].kwargs["filters"],
			{"campaign": ["in", ["C2"]], "channel": "CHANNEL-1"})
		self.assertEqual(all_query.call_args_list[0].kwargs["filters"],
			[["attributed_at", ">=", "2026-08-01"], ["attributed_at", "<", "2026-09-01"]])

	def test_cohort_initializes_all_visible_campaigns_without_campus_filter(self):
		api = director_campaign_intelligence
		attributions = [{"name": "A", "student": "S1", "campaign": "C1", "is_first_touch": 1}]
		def get_all(doctype, **kwargs):
			return {
				"CRM Campaign Attribution": attributions,
				"CRM Enrollment Status": [{"name": "NEW", "display_name": "Mới"}],
			}[doctype]
		with patch.object(frappe.db, "table_exists", return_value=True), \
			patch.object(frappe, "get_all", side_effect=get_all), \
			patch.object(frappe, "get_list", side_effect=[
				[{"name": "C1"}],
				[{"name": "S1", "processing_status": "NEW", "resolution": "PENDING"}],
			]), \
			patch.object(frappe.db, "get_value", return_value="YEAR-2026"):
			result = api._load_campaign_lead_rows("2026", date(2026, 1, 1), date(2026, 12, 31), None, None,
				{"territory": None})

		self.assertEqual([row["name"] for row in result["C1"]], ["S1"])

	def test_drilldown_validates_pagination_and_status_before_loading_students(self):
		api = director_campaign_intelligence
		with patch.object(api, "require_campaign_intelligence_access", return_value={}), \
			patch.object(api, "resolve_admission_year", return_value="2026"), \
			patch.object(api, "_resolve_date_range", return_value=(date(2026, 1, 1), date(2026, 12, 31), [])), \
			patch.object(api, "_load_campaign_lead_page") as load:
			for params in ({"page": 0}, {"pageSize": 101}, {"page": "1.5"}, {"statusGroup": "bad"},
				{"campaignId": ""}):
				with self.subTest(params=params), self.assertRaises(frappe.ValidationError):
					api.get_campaign_leads(**{"campaignId": "C1", **params})
			load.assert_not_called()

	def test_drilldown_denies_before_querying_data(self):
		api = director_campaign_intelligence
		with patch.object(api, "require_campaign_intelligence_access", side_effect=frappe.PermissionError), \
			patch.object(api, "_load_campaign_lead_page") as load:
			with self.assertRaises(frappe.PermissionError):
				api.get_campaign_leads("C1")
			load.assert_not_called()

	def test_drilldown_paginates_filtered_cohort_and_keeps_minimal_fields(self):
		api = director_campaign_intelligence
		rows = [{"name": f"S{i}", "lead_code": f"LD-2026-0000{i}", "student_name": f"Student {i}", "processing_status": "NEW", "resolution": "PENDING",
			"status": "Mới", "statusCode": "NEW", "statusGroup": "new", "modified": "2026-08-01",
			"phone": "SHOULD-NOT-LEAK", "email": "SHOULD-NOT-LEAK"} for i in range(3)]
		with patch.object(api, "require_campaign_intelligence_access", return_value={}), \
			patch.object(api, "resolve_admission_year", return_value="2026"), \
			patch.object(api, "_resolve_date_range", return_value=(date(2026, 1, 1), date(2026, 12, 31), [])), \
			patch.object(api, "_resolve_scope", return_value={"id": "all", "territory": None}), \
			patch.object(api, "_resolve_link_filter", return_value=None), \
			patch.object(api, "_load_campaign_lead_page", return_value={"rows": [rows[2]], "total": 3}), \
			patch.object(frappe, "get_list", side_effect=[[{"name": "C1"}], []]):
			response = api.get_campaign_leads("C1", page=2, pageSize=2, statusGroup="new")
		self.assertEqual(response["pagination"], {"page": 2, "pageSize": 2, "total": 3, "totalPages": 2})
		self.assertEqual(response["items"][0]["id"], "S2")
		self.assertEqual(response["items"][0]["leadCode"], "LD-2026-00002")
		self.assertEqual(set(response["items"][0]), {"id", "leadCode", "name", "school", "status", "statusCode",
			"statusGroup", "owner", "source", "contactAttemptCount", "lastContactAt", "modifiedAt"})

	def test_contact_attempt_count_uses_outbound_contact_evidence(self):
		api = director_campaign_intelligence
		row = {"name": "S1", "status": "Mới", "statusCode": "NEW", "statusGroup": "new"}
		with patch.object(frappe, "get_list", return_value=[
			{"student": "S1", "interaction_datetime": "2026-08-01 10:00:00"},
			{"student": "S1", "interaction_datetime": "2026-08-02 10:00:00"},
		]) as query:
			item = api._build_lead_items([row])[0]
		self.assertEqual(item["contactAttemptCount"], 2)
		self.assertEqual(item["lastContactAt"], "2026-08-02 10:00:00")
		self.assertEqual(query.call_args.kwargs["filters"]["direction"], "outbound")

	def test_lead_detail_returns_unavailable_when_lead_source_is_missing(self):
		api = director_campaign_intelligence
		with patch.object(api, "require_campaign_intelligence_access", return_value={}), \
			patch.object(api, "resolve_admission_year", return_value="2026"), \
			patch.object(api, "_resolve_date_range", return_value=(date(2026, 1, 1), date(2026, 12, 31), [])), \
			patch.object(frappe, "get_list", return_value=[{"name": "C1"}]), \
			patch.object(api, "_resolve_scope", return_value={"id": "all", "territory": None}), \
			patch.object(api, "_resolve_link_filter", return_value=None), \
			patch.object(api, "_load_campaign_lead_page", return_value=None):
			with self.assertRaises(frappe.ValidationError):
				api.get_campaign_leads("C1")
