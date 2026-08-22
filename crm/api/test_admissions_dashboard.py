import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.admissions_dashboard import (
	_contact_names_touched_by_campaign,
	_contact_names_with_event_participation,
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

	# ------------------------------------------------------------------------
	# Phase 5: dashboard helpers must union the deprecated singular
	# crm_campaign/crm_event Link fields on CRM Contact with the new
	# CRM Campaign Touchpoint / CRM Event Participation junction tables, so
	# dashboards read correctly whether attribution predates or postdates
	# the Phase 5 migration.

	def test_contact_names_touched_by_campaign_unions_old_and_new_attribution(self):
		campus = self._make_campus_for_dash("_Test Dash Union Campus")
		campaign = self._make_campaign_for_dash("_Test Dash Union Campaign", campus)

		legacy_contact = self._make_dash_contact(
			"_Test Dash Legacy Attribution", "0981112224", crm_campaign=campaign
		)
		migrated_contact = self._make_dash_contact("_Test Dash New Attribution", "0981112225")
		touchpoint = frappe.get_doc(
			{
				"doctype": "CRM Campaign Touchpoint",
				"crm_campaign": campaign,
				"crm_contact": migrated_contact,
			}
		)
		touchpoint.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Campaign Touchpoint", touchpoint.name, force=True))

		names = _contact_names_touched_by_campaign(campaign)

		self.assertIn(legacy_contact, names)
		self.assertIn(migrated_contact, names)

	def test_contact_names_with_event_participation_unions_old_and_new_attribution(self):
		campus = self._make_campus_for_dash("_Test Dash Union Event Campus")
		campaign = self._make_campaign_for_dash("_Test Dash Union Event Campaign", campus)
		event = self._make_event_for_dash("_Test Dash Union Event", campaign)

		legacy_contact = self._make_dash_contact(
			"_Test Dash Legacy Event Attribution", "0981112226", crm_event=event
		)
		migrated_contact = self._make_dash_contact("_Test Dash New Event Attribution", "0981112227")
		participation = frappe.get_doc(
			{
				"doctype": "CRM Event Participation",
				"crm_event": event,
				"crm_contact": migrated_contact,
			}
		)
		participation.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Event Participation", participation.name, force=True))

		names = _contact_names_with_event_participation()

		self.assertIn(legacy_contact, names)
		self.assertIn(migrated_contact, names)

	# ------------------------------------------------------------- helpers

	def _make_campus_for_dash(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Campus", doc.name, force=True))
		return doc.name

	def _make_campaign_for_dash(self, title, campus):
		if frappe.db.exists("CRM Campaign", title):
			frappe.delete_doc("CRM Campaign", title, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campaign", "title": title, "campus": campus})
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Campaign", doc.name, force=True))
		return doc.name

	def _make_event_for_dash(self, title, campaign):
		if frappe.db.exists("CRM Event", title):
			frappe.delete_doc("CRM Event", title, force=True)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Event",
				"title": title,
				"crm_campaign": campaign,
				"start_datetime": "2026-09-01 09:00:00",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Event", doc.name, force=True))
		return doc.name

	def _make_dash_contact(self, name, phone, crm_campaign=None, crm_event=None):
		payload = {
			"doctype": "CRM Contact",
			"full_name": name,
			"phone": phone,
			"enrollment_status": "Có triển vọng",
		}
		if crm_campaign:
			payload["crm_campaign"] = crm_campaign
		if crm_event:
			payload["crm_event"] = crm_event
		contact = frappe.get_doc(payload)
		contact.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Contact", contact.name, force=True))
		return contact.name
