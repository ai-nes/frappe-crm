# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.exceptions import MandatoryError
from frappe.tests.utils import FrappeTestCase


class TestCRMCampaignSpend(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("CRM Lead Source", "_Test Spend Source"):
			frappe.get_doc(
				{
					"doctype": "CRM Lead Source",
					"source_name": "_Test Spend Source",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		for name in frappe.db.get_all("CRM Campaign Spend", filters={"lead_source": "_Test Spend Source"}, pluck="name"):
			frappe.delete_doc("CRM Campaign Spend", name, force=True)
		if frappe.db.exists("CRM Lead Source", "_Test Spend Source"):
			frappe.delete_doc("CRM Lead Source", "_Test Spend Source", force=True)

	def test_create_campaign_spend(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Campaign Spend",
				"spend_date": "2026-08-19",
				"lead_source": "_Test Spend Source",
				"amount": 5000000,
				"impressions": 10000,
				"clicks": 450,
			}
		).insert(ignore_permissions=True)

		self.assertTrue(doc.name.startswith("SPEND-"))
		self.assertEqual(doc.amount, 5000000)
		self.assertEqual(doc.lead_source, "_Test Spend Source")

	def test_mandatory_fields(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Campaign Spend",
				"amount": 1000000,
			}
		)
		with self.assertRaises(MandatoryError):
			doc.insert(ignore_permissions=True)
