from frappe.tests.utils import FrappeTestCase

from crm.demo import seed_director_campaign_intelligence


class TestSeedDirectorCampaignIntelligence(FrappeTestCase):
	def test_weekly_observations_are_complete_and_support_campaign_comparison(self):
		strong = seed_director_campaign_intelligence._weekly_observations(0)
		weak = seed_director_campaign_intelligence._weekly_observations(1)

		self.assertEqual(len(strong), 4)
		self.assertTrue(all(row["spend"] > 0 and row["confirmed_revenue"] > 0 for row in strong))
		self.assertGreater(
			sum(row["confirmed_revenue"] for row in strong) / sum(row["spend"] for row in strong),
			sum(row["confirmed_revenue"] for row in weak) / sum(row["spend"] for row in weak),
		)
