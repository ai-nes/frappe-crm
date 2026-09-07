import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.campaign_channel_type_catalog import CAMPAIGN_CHANNEL_TYPE_CATALOG
from crm.patches.v1_0.seed_campaign_channel_type import execute


class TestSeedCampaignChannelType(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		execute()

	def tearDown(self):
		frappe.db.rollback()

	def test_seed_contains_all_catalog_values_and_modes(self):
		rows = frappe.get_all(
			"CRM Campaign Channel Type",
			fields=["code", "display_name", "is_online", "is_offline", "sort_order"],
			filters={"code": ["in", [code for code, _, _ in CAMPAIGN_CHANNEL_TYPE_CATALOG]]},
			order_by="sort_order asc",
			limit_page_length=0,
		)
		self.assertEqual(len(rows), len(CAMPAIGN_CHANNEL_TYPE_CATALOG))
		for row, (code, display_name, modes) in zip(rows, CAMPAIGN_CHANNEL_TYPE_CATALOG, strict=True):
			self.assertEqual(row.code, code)
			self.assertEqual(row.display_name, display_name)
			self.assertEqual(bool(row.is_online), "ONLINE" in modes)
			self.assertEqual(bool(row.is_offline), "OFFLINE" in modes)

	def test_seed_is_idempotent(self):
		execute()
		self.assertEqual(
			frappe.db.count("CRM Campaign Channel Type"),
			len(CAMPAIGN_CHANNEL_TYPE_CATALOG),
		)
