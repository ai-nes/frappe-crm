import uuid

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.campaign import (
	create_campaign,
	delete_campaign,
	get_campaign,
	list_campaigns,
	update_campaign,
)


class TestCampaignApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")
		self._suffix = uuid.uuid4().hex[:8]
		self.campus = self._make_campus()

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Campaign",
			filters={"title": ["like", f"_Test Campaign API {self._suffix}%"]},
			pluck="name",
		):
			frappe.delete_doc("CRM Campaign", name, force=True)
		if frappe.db.exists("CRM Campus", self.campus):
			frappe.delete_doc("CRM Campus", self.campus, force=True)
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def _make_campus(self):
		campus = frappe.get_doc(
			{"doctype": "CRM Campus", "campus_name": f"_Test Campaign API Campus {self._suffix}"}
		)
		campus.insert(ignore_permissions=True)
		return campus.name

	def _create_campaign(self, **values):
		return create_campaign(
			title=f"_Test Campaign API {self._suffix} {uuid.uuid4().hex[:6]}",
			campus=self.campus,
			**values,
		)

	def test_campaign_crud_and_filtered_list(self):
		created = self._create_campaign(
			status="ACTIVE",
			start_date="2026-09-01",
			end_date="2026-09-30",
			budget=125000,
			utm_campaign="autumn-admissions",
		)

		self.assertEqual(get_campaign(created["name"])["stable_code"], created["stable_code"])
		updated = update_campaign(created["name"], status="CLOSED", notes="Updated through API")
		self.assertEqual(updated["status"], "CLOSED")
		self.assertEqual(updated["notes"], "Updated through API")

		listed = list_campaigns(
			status="CLOSED",
			campus=self.campus,
			start_date_from="2026-09-01",
			start_date_to="2026-09-30",
			search="autumn-admissions",
		)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["campaigns"][0]["name"], created["name"])

		self.assertEqual(delete_campaign(created["name"]), {"deleted": created["name"]})
		self.assertFalse(frappe.db.exists("CRM Campaign", created["name"]))

	def test_campaign_code_is_server_managed(self):
		created = self._create_campaign()

		with self.assertRaises(frappe.ValidationError):
			update_campaign(created["name"], stable_code="CAM-2026-99999")

		self.assertEqual(get_campaign(created["name"])["stable_code"], created["stable_code"])
