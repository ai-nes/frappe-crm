import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.campaign_channel_type_catalog import CAMPAIGN_CHANNEL_TYPE_CATALOG
from crm.patches.v1_0.seed_campaign_channel_sources import execute


class TestSeedCampaignChannelSources(FrappeTestCase):
	def setUp(self):
		self.created_sources = []

	def tearDown(self):
		for source in self.created_sources:
			if self._exists(source):
				self._delete(source)

	def _exists(self, source):
		return frappe.db.exists("CRM Lead Source", source)

	def _delete(self, source):
		frappe.delete_doc("CRM Lead Source", source, force=True)

	def test_execute_seeds_channel_display_names_idempotently(self):
		for _code, display_name, _modes in CAMPAIGN_CHANNEL_TYPE_CATALOG:
			if not frappe.db.exists("CRM Lead Source", display_name):
				self.created_sources.append(display_name)

		execute()
		execute()

		for _code, display_name, _modes in CAMPAIGN_CHANNEL_TYPE_CATALOG:
			self.assertTrue(frappe.db.exists("CRM Lead Source", display_name))
