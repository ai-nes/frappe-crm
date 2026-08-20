import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.admissions_dashboard import (
	get_digital_marketing_dashboard,
	get_offline_marketing_dashboard,
	get_sales_dashboard,
)


class TestAdmissionsDashboard(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("CRM Lead Source", "_Test Dash Source"):
			frappe.get_doc(
				{
					"doctype": "CRM Lead Source",
					"source_name": "_Test Dash Source",
					"is_digital": 1,
					"channel_family": "Social",
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("CRM Contact", "CRMC-TEST-DASH-01"):
			frappe.get_doc(
				{
					"doctype": "CRM Contact",
					"name": "CRMC-TEST-DASH-01",
					"full_name": "_Test Dash Student",
					"phone": "0981112223",
					"source": "_Test Dash Source",
					"enrollment_status": "Có triển vọng",
					"lead_status": "Mới",
					"is_test_record": 0,
					"readiness_level": "Level 2 - Đang so sánh",
					"quality_bucket": "Hot",
					"is_verified_lead": 1,
					"sla_status": "Đúng SLA",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		if frappe.db.exists("CRM Contact", "CRMC-TEST-DASH-01"):
			frappe.delete_doc("CRM Contact", "CRMC-TEST-DASH-01", force=True)
		if frappe.db.exists("CRM Lead Source", "_Test Dash Source"):
			frappe.delete_doc("CRM Lead Source", "_Test Dash Source", force=True)

	def test_get_sales_dashboard(self):
		items = get_sales_dashboard(from_date="2020-01-01", to_date="2030-12-31")
		self.assertIsInstance(items, list)
		self.assertGreaterEqual(len(items), 5)
		item_names = [it["name"] for it in items]
		self.assertIn("mock_new_leads", item_names)
		self.assertIn("mock_admission_funnel", item_names)

	def test_get_digital_marketing_dashboard(self):
		items = get_digital_marketing_dashboard(from_date="2020-01-01", to_date="2030-12-31")
		self.assertIsInstance(items, list)
		self.assertGreaterEqual(len(items), 5)
		item_names = [it["name"] for it in items]
		self.assertIn("mock_marketing_leads", item_names)
		self.assertIn("mock_leads_by_platform", item_names)

	def test_get_offline_marketing_dashboard(self):
		items = get_offline_marketing_dashboard(team="all", from_date="2020-01-01", to_date="2030-12-31")
		self.assertIsInstance(items, list)
		self.assertEqual(len(items), 4)
		item_names = [it["name"] for it in items]
		self.assertIn("mock_offline_region", item_names)
		self.assertIn("mock_offline_province", item_names)
