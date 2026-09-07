import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.campaign_channel_type import list_campaign_channel_types
from crm.fcrm.campaign_channel_type_catalog import CAMPAIGN_CHANNEL_TYPE_CATALOG


class TestCampaignChannelTypeApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def test_lists_catalog_values_with_modes(self):
		result = list_campaign_channel_types()

		self.assertEqual(result["total"], len(CAMPAIGN_CHANNEL_TYPE_CATALOG))
		self.assertEqual(len(result["channel_types"]), len(CAMPAIGN_CHANNEL_TYPE_CATALOG))
		first = result["channel_types"][0]
		self.assertEqual(first["code"], "FACEBOOK_LEAD_FORM")
		self.assertEqual(first["modes"], ["ONLINE"])

	def test_filters_by_mode_and_search(self):
		online = list_campaign_channel_types(mode="online")
		self.assertEqual(online["total"], 13)
		self.assertTrue(all("ONLINE" in row["modes"] for row in online["channel_types"]))

		search = list_campaign_channel_types(mode="OFFLINE", search="Experience Day")
		self.assertEqual(search["total"], 1)
		self.assertEqual(search["channel_types"][0]["code"], "EXPERIENCE_DAY")

	def test_rejects_unknown_mode(self):
		with self.assertRaises(frappe.ValidationError):
			list_campaign_channel_types(mode="HYBRID")
