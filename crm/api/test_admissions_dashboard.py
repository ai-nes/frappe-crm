import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.admissions_dashboard import (
	_campaign_cost_data,
	_contact_names_touched_by_campaign,
	_contact_names_with_event_participation,
	get_admissions_director_dashboard,
	get_digital_marketing_dashboard,
	get_offline_marketing_dashboard,
	get_sales_dashboard,
)
from crm.api.admissions_dashboard_auth import DashboardAccessDenied


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

	# ------------------------------------------------------------------------
	# Phase 6: campaign-scoped total_spend and per-campaign cost data

	def test_digital_dashboard_total_spend_scoped_to_selected_campaign(self):
		campus = self._make_campus_for_dash("_Test Dash Spend Campus")
		campaign_a = self._make_campaign_for_dash("_Test Dash Spend Campaign A", campus)
		campaign_b = self._make_campaign_for_dash("_Test Dash Spend Campaign B", campus)

		self._make_campaign_spend(campaign_a, "2020-06-01", 100000)
		self._make_campaign_spend(campaign_b, "2020-06-01", 500000)

		# Smoke-check the dashboard still returns a well-formed response with
		# the `campaign` filter set (the mock_campaign_cost chart's row list
		# is bounded/unordered by CRM Campaign query -- see
		# test_campaign_cost_data_scopes_spend_per_campaign below for a
		# direct assertion against the real per-campaign spend values, via
		# the same _campaign_cost_data helper get_digital_marketing_dashboard
		# calls internally).
		items = get_digital_marketing_dashboard(
			from_date="2020-01-01", to_date="2030-12-31", campaign=campaign_a
		)
		item_names = [it["name"] for it in items]
		self.assertIn("mock_cpl", item_names)
		self.assertIn("mock_campaign_cost", item_names)

	def test_campaign_cost_data_scopes_spend_per_campaign(self):
		# Directly exercises _campaign_cost_data, the exact helper both
		# get_digital_marketing_dashboard and get_admissions_director_dashboard
		# call -- if the campaign-scoping filter inside it ever regresses back
		# to an unscoped/flat spend total, this test fails against the real
		# production code path (not a reimplementation of the query).
		campus = self._make_campus_for_dash("_Test Dash Spend Only Campus")
		campaign_a = self._make_campaign_for_dash("_Test Dash Spend Only Campaign A", campus)
		campaign_b = self._make_campaign_for_dash("_Test Dash Spend Only Campaign B", campus)

		self._make_campaign_spend(campaign_a, "2020-06-01", 100000)
		self._make_campaign_spend(campaign_b, "2020-06-01", 500000)

		campaign_list = [
			frappe._dict({"name": campaign_a, "title": None}),
			frappe._dict({"name": campaign_b, "title": None}),
		]
		cost_data = _campaign_cost_data(campaign_list, "2020-01-01", "2030-12-31", base_filters=[])
		spend_by_campaign = {row["campaign"]: row["spend"] for row in cost_data}
		self.assertEqual(spend_by_campaign[campaign_a], 100000)
		self.assertEqual(spend_by_campaign[campaign_b], 500000)

	# ------------------------------------------------------------------------
	# Phase 6: admissions director dashboard role gate + shape

	def test_get_admissions_director_dashboard_denied_for_unauthorized_role(self):
		user, staff = self._make_user_and_staff_for_dash("_test_director_denied", roles=["Sale"])
		try:
			with self.assertRaises(DashboardAccessDenied):
				self._call_as_user(
					user, get_admissions_director_dashboard, from_date="2020-01-01", to_date="2030-12-31"
				)
		finally:
			self._cleanup_user_and_staff_for_dash(user, staff)

	def test_get_admissions_director_dashboard_returns_chart_list_for_authorized_role(self):
		frappe.set_user("Administrator")
		items = get_admissions_director_dashboard(from_date="2020-01-01", to_date="2030-12-31")
		self.assertIsInstance(items, list)
		self.assertGreater(len(items), 0)
		item_names = [it["name"] for it in items]
		self.assertIn("director_total_leads", item_names)
		self.assertIn("director_campaign_cost", item_names)
		self.assertIn("director_multi_touch_credit", item_names)

	def test_get_admissions_director_dashboard_allows_admissions_director_role(self):
		# Unlike the Administrator smoke-check above, this exercises the new,
		# narrower "admissions_director" gate itself: a user holding ONLY the
		# Admissions Director role (no Administrator/System Manager) must be
		# let through. Admissions Director is also in ADMIN_ROLES (Phase 6),
		# so it bypasses get_campus_scope's CRM Staff lookup -- no CRM Staff
		# fixture is needed for this role specifically.
		user, staff = self._make_user_and_staff_for_dash(
			"_test_director_allowed", roles=["Admissions Director"]
		)
		try:
			items = self._call_as_user(
				user, get_admissions_director_dashboard, from_date="2020-01-01", to_date="2030-12-31"
			)
			self.assertIsInstance(items, list)
			item_names = [it["name"] for it in items]
			self.assertIn("director_total_leads", item_names)
		finally:
			self._cleanup_user_and_staff_for_dash(user, staff)

	# ------------------------------------------------------------------- helpers (Phase 6)

	def _make_campaign_spend(self, campaign, spend_date, amount):
		if not frappe.db.exists("CRM Lead Source", "_Test Dash Spend Source"):
			frappe.get_doc(
				{"doctype": "CRM Lead Source", "source_name": "_Test Dash Spend Source"}
			).insert(ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Campaign Spend",
				"crm_campaign": campaign,
				"lead_source": "_Test Dash Spend Source",
				"spend_date": spend_date,
				"amount": amount,
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.delete_doc("CRM Campaign Spend", doc.name, force=True))
		return doc.name

	def _make_user_and_staff_for_dash(self, prefix, roles=None):
		email = f"{prefix}@example.com"
		if frappe.db.exists("User", email):
			frappe.delete_doc("User", email, force=True)
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": prefix,
				"send_welcome_email": 0,
				"roles": [{"role": role} for role in (roles or ["Sale"])],
			}
		)
		user.insert(ignore_permissions=True)
		return email, None

	def _cleanup_user_and_staff_for_dash(self, user, staff):
		if user and frappe.db.exists("User", user):
			frappe.delete_doc("User", user, force=True)
		frappe.set_user("Administrator")

	def _call_as_user(self, user, fn, **kwargs):
		frappe.set_user(user)
		try:
			return fn(**kwargs)
		finally:
			frappe.set_user("Administrator")

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
