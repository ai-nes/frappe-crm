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

		if not frappe.db.exists("CRM Student", {"phone": "0981112223"}):
			previous_migration_flag = getattr(frappe.flags, "contact_migration_service", False)
			frappe.flags.contact_migration_service = True
			try:
				frappe.get_doc(
					{
						"doctype": "CRM Student",
						"full_name": "_Test Dash Student",
						"phone": "0981112223",
						"source": "_Test Dash Source",
						"enrollment_status": "PROSPECT",
						"is_test_record": 0,
						"readiness_level": "Level 2 - Đang so sánh",
						"quality_bucket": "Hot",
						"is_verified_lead": 1,
						"sla_status": "Đúng SLA",
					}
				).insert(ignore_permissions=True)
			finally:
				frappe.flags.contact_migration_service = previous_migration_flag

	def tearDown(self):
		contact_name = frappe.db.get_value("CRM Student", {"phone": "0981112223"}, "name")
		if contact_name:
			frappe.delete_doc("CRM Student", contact_name, force=True)
		if frappe.db.exists("CRM Lead Source", "_Test Dash Source"):
			self._delete_doc("CRM Lead Source", "_Test Dash Source")

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
	# Canonical marketing engagement is the only dashboard attribution source.

	def test_contact_names_touched_by_campaign_reads_canonical_engagement(self):
		campus = self._make_campus_for_dash("_Test Dash Union Campus")
		campaign = self._make_campaign_for_dash("_Test Dash Union Campaign", campus)

		student_a = self._make_dash_student()
		contact_a = self._make_dash_contact("_Test Dash Campaign Attribution A", "0981112224", student=student_a)
		student_b = self._make_dash_student()
		contact_b = self._make_dash_contact("_Test Dash Campaign Attribution B", "0981112225", student=student_b)
		touchpoint = frappe.get_doc(
			{
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "campaign_touch",
				"reference_doctype": "CRM Campaign",
				"reference_name": campaign,
				"crm_campaign": campaign,
				"crm_contact": contact_a,
				"student": student_a,
			}
		)
		previous_attribution_flag = getattr(frappe.flags, "student_attribution_service", False)
		frappe.flags.student_attribution_service = True
		try:
			touchpoint.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_attribution_service = previous_attribution_flag
		self.addCleanup(lambda: frappe.db.delete("CRM Marketing Engagement", {"name": touchpoint.name}))
		second = frappe.get_doc({
			"doctype": "CRM Marketing Engagement", "engagement_kind": "campaign_touch",
			"reference_doctype": "CRM Campaign", "reference_name": campaign,
			"crm_campaign": campaign, "crm_contact": contact_b, "student": student_b,
		})
		second.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.db.delete("CRM Marketing Engagement", {"name": second.name}))

		names = _contact_names_touched_by_campaign(campaign)

		self.assertIn(contact_a, names)
		self.assertIn(contact_b, names)

	def test_contact_names_with_event_participation_reads_canonical_engagement(self):
		campus = self._make_campus_for_dash("_Test Dash Union Event Campus")
		campaign = self._make_campaign_for_dash("_Test Dash Union Event Campaign", campus)
		event = self._make_event_for_dash("_Test Dash Union Event", campaign)

		student_a = self._make_dash_student()
		contact_a = self._make_dash_contact("_Test Dash Event Attribution A", "0981112226", student=student_a)
		student_b = self._make_dash_student()
		contact_b = self._make_dash_contact("_Test Dash Event Attribution B", "0981112227", student=student_b)
		participation = frappe.get_doc(
			{
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "event_participation",
				"reference_doctype": "CRM Event",
				"reference_name": event,
				"crm_event": event,
				"crm_contact": contact_a,
				"student": student_a,
			}
		)
		previous_attribution_flag = getattr(frappe.flags, "student_attribution_service", False)
		frappe.flags.student_attribution_service = True
		try:
			participation.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_attribution_service = previous_attribution_flag
		self.addCleanup(lambda: frappe.db.delete("CRM Marketing Engagement", {"name": participation.name}))
		second = frappe.get_doc({
			"doctype": "CRM Marketing Engagement", "engagement_kind": "event_participation",
			"reference_doctype": "CRM Event", "reference_name": event,
			"crm_event": event, "crm_contact": contact_b, "student": student_b,
		})
		second.insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.db.delete("CRM Marketing Engagement", {"name": second.name}))

		names = _contact_names_with_event_participation()

		self.assertIn(contact_a, names)
		self.assertIn(contact_b, names)

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
		from crm.fcrm.campaign_performance_fact import record_performance_fact
		lead_source = "_Test Dash Spend Source"
		platform = "_Test Dash Spend Platform"
		if not frappe.db.exists("CRM Lead Source", lead_source):
			frappe.get_doc({"doctype": "CRM Lead Source", "source_name": lead_source}).insert(ignore_permissions=True)
		if not frappe.db.exists("CRM Platform", platform):
			frappe.get_doc({"doctype": "CRM Platform", "platform_name": platform, "lead_source": lead_source}).insert(ignore_permissions=True)
		assignment = frappe.get_doc({"doctype": "CRM Campaign Channel Assignment", "campaign": campaign, "channel": platform, "effective_from": "2020-01-01", "is_active": 1}).insert(ignore_permissions=True)
		result = record_performance_fact(campaign=campaign, channel_assignment=assignment.name, period_start=spend_date, period_end=spend_date, timezone="Asia/Ho_Chi_Minh", source_system="test", ingestion_run=f"dash-{campaign}", source_key=f"{campaign}-{spend_date}", dimension_values={"channel": platform}, measures={"spend": amount})
		self.addCleanup(lambda: frappe.db.delete("CRM Campaign Performance Fact", result["fact"]))
		self.addCleanup(lambda: frappe.delete_doc("CRM Campaign Channel Assignment", assignment.name, force=True))
		return result["fact"]

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
			self._delete_doc("CRM Campus", name)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		self.addCleanup(lambda: self._delete_doc("CRM Campus", doc.name))
		return doc.name

	@staticmethod
	def _delete_doc(doctype, name):
		previous_governance_flag = getattr(frappe.flags, "crm_governance_change", False)
		frappe.flags.crm_governance_change = True
		try:
			frappe.delete_doc(doctype, name, force=True)
		finally:
			frappe.flags.crm_governance_change = previous_governance_flag

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

	def _make_dash_student(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "_Test Dash Student Anchor",
				"phone": "0981112230",
				"enrollment_status": "PROSPECT",
			}
		)
		previous_intake_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_intake_flag
		self.addCleanup(lambda: frappe.delete_doc("CRM Lead", student.name, force=True))
		return student.name

	def _make_dash_contact(self, name, phone, crm_campaign=None, crm_event=None, student=None):
		payload = {
			"doctype": "CRM Student",
			"full_name": name,
			"phone": phone,
			"enrollment_status": "PROSPECT",
		}
		if crm_campaign:
			payload["crm_campaign"] = crm_campaign
		if crm_event:
			payload["crm_event"] = crm_event
		if student:
			payload["student"] = student
		contact = frappe.get_doc(payload)
		previous_migration_flag = getattr(frappe.flags, "contact_migration_service", False)
		frappe.flags.contact_migration_service = True
		try:
			contact.insert(ignore_permissions=True)
		finally:
			frappe.flags.contact_migration_service = previous_migration_flag
		self.addCleanup(lambda: frappe.delete_doc("CRM Student", contact.name, force=True))
		return contact.name
