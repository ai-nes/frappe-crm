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
		):
			response = director_campaign_intelligence.get_director_campaign_intelligence("2026")

		self.assertEqual(
			set(response),
			{"meta", "generatedAt", "summary", "trend", "funnel", "campaigns", "recommendation"},
		)
		self.assertEqual(response["summary"]["spend"], 0.0)
		self.assertEqual(len(response["funnel"]), 7)
