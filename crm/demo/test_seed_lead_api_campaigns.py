import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.demo.seed_lead_api_campaigns import LEAD_API_CAMPAIGNS, execute


class TestSeedLeadAPICampaigns(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.suffix = uuid.uuid4().hex[:8]
		self.extra_campaign_names = []
		self.campus = frappe.get_doc(
			{
				"doctype": "CRM Campus",
				"campus_name": f"_Test Lead API Campaign Campus {self.suffix}",
			}
		).insert(ignore_permissions=True)
		self.specs = tuple(
			{
				**spec,
				"code": f"CAM-2026-{99000 + index:05d}",
				"title": f"_Test Lead API Campaign {self.suffix} {index}",
			}
			for index, spec in enumerate(LEAD_API_CAMPAIGNS, start=1)
		)

	def tearDown(self):
		for spec in self.specs:
			name = frappe.db.get_value("CRM Campaign", {"title": spec["title"]}, "name")
			if name:
				frappe.delete_doc("CRM Campaign", name, force=True)
		for name in self.extra_campaign_names:
			if frappe.db.exists("CRM Campaign", name):
				frappe.delete_doc("CRM Campaign", name, force=True)
		if frappe.db.exists("CRM Campus", self.campus.name):
			frappe.delete_doc("CRM Campus", self.campus.name, force=True)
		frappe.db.rollback()

	def test_seed_creates_four_campaigns_and_is_idempotent(self):
		first = execute(campus=self.campus.name, campaign_specs=self.specs)
		second = execute(campus=self.campus.name, campaign_specs=self.specs)

		self.assertEqual(first["created"], 4)
		self.assertEqual(second["created"], 0)
		self.assertEqual([row["code"] for row in first["campaigns"]], [spec["code"] for spec in self.specs])
		self.assertEqual(
			frappe.db.count("CRM Campaign", {"title": ["like", f"_Test Lead API Campaign {self.suffix}%"]}),
			4,
		)

	def test_seed_reuses_existing_campaign_when_code_has_another_title(self):
		existing = frappe.get_doc(
			{
				"doctype": "CRM Campaign",
				"title": f"_Test Existing Campaign {self.suffix}",
				"campus": self.campus.name,
				"status": "ACTIVE",
				"start_date": "2026-01-01",
				"end_date": "2026-12-31",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Campaign", existing.name, "stable_code", self.specs[0]["code"])
		self.extra_campaign_names.append(existing.name)

		result = execute(campus=self.campus.name, campaign_specs=self.specs)

		self.assertEqual(result["created"], 3)
		self.assertEqual(result["existing"], 1)
		self.assertEqual(result["campaigns"][0]["name"], existing.name)
		self.assertEqual(result["campaigns"][0]["title"], existing.title)
