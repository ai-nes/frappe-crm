import uuid
from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import campaign as campaign_api
from crm.api.campaign import (
	create_campaign,
	delete_campaign,
	get_campaign,
	get_public_campaigns,
	list_campaigns,
	update_campaign,
)


class TestPublicCampaignApi(TestCase):
	def test_public_campaigns_filter_dates_and_paginate(self):
		rows = [
			{
				"name": "Campaign 1",
				"stable_code": "CAM-2026-00001",
				"title": "Website 2026",
				"campus": "HCM",
				"status": "ACTIVE",
				"start_date": "2026-09-01",
				"end_date": "2026-09-30",
			}
		]
		with (
			patch.object(campaign_api.frappe, "get_all", return_value=rows) as get_all,
			patch.object(campaign_api.frappe.db, "count", return_value=1) as count,
		):
			result = get_public_campaigns(
				campaign_code="CAM-2026-00001",
				startdate="2026-09-01",
				enddate="2026-09-30",
				start="10",
				page_length="25",
			)

		self.assertEqual(result, {"total": 1, "start": 10, "page_length": 25, "campaigns": rows})
		filters = [
			["stable_code", "=", "CAM-2026-00001"],
			["start_date", ">=", "2026-09-01"],
			["end_date", "<=", "2026-09-30"],
		]
		self.assertEqual(get_all.call_args.kwargs["filters"], filters)
		self.assertEqual(get_all.call_args.kwargs["fields"], list(campaign_api.PUBLIC_CAMPAIGN_FIELDS))
		self.assertEqual(get_all.call_args.kwargs["limit_start"], 10)
		self.assertEqual(get_all.call_args.kwargs["limit_page_length"], 25)
		count.assert_called_once_with("CRM Campaign", filters=filters)

	def test_public_campaigns_accept_snake_case_date_aliases(self):
		with (
			patch.object(campaign_api.frappe, "get_all", return_value=[]),
			patch.object(campaign_api.frappe.db, "count", return_value=0),
		):
			result = get_public_campaigns(
				start_date="2026-09-01",
				end_date="2026-09-30",
			)

		self.assertEqual(result["total"], 0)

	def test_public_campaigns_reject_invalid_dates_and_pagination(self):
		with self.assertRaises(frappe.ValidationError):
			get_public_campaigns(startdate="2026-10-01", enddate="2026-09-01")
		with self.assertRaises(frappe.ValidationError):
			get_public_campaigns(startdate="2026/09/01")
		with self.assertRaises(frappe.ValidationError):
			get_public_campaigns(page_length=101)

	def test_public_campaigns_are_guest_whitelisted(self):
		source = campaign_api.__loader__.get_source(campaign_api.__name__)
		self.assertIn('@frappe.whitelist(allow_guest=True, methods=["GET"])', source)


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
			channel_type="OPEN_DAY",
			channel_url="https://example.com/open-day",
			budget=125000,
			utm_campaign="autumn-admissions",
		)

		self.assertEqual(get_campaign(code=created["stable_code"])["name"], created["name"])
		self.assertEqual(created["channel_type"], "OPEN_DAY")
		self.assertEqual(created["channel_url"], "https://example.com/open-day")
		updated = update_campaign(
			created["name"],
			status="CLOSED",
			notes="Updated through API",
			channel_type="EXPERIENCE_DAY",
			channel_url="https://example.com/experience-day",
		)
		self.assertEqual(updated["status"], "CLOSED")
		self.assertEqual(updated["notes"], "Updated through API")
		self.assertEqual(updated["channel_type"], "EXPERIENCE_DAY")
		self.assertEqual(updated["channel_url"], "https://example.com/experience-day")

		listed = list_campaigns(
			status="CLOSED",
			campus=self.campus,
			channel_type="EXPERIENCE_DAY",
			start_date_from="2026-09-01",
			start_date_to="2026-09-30",
			search="autumn-admissions",
		)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["campaigns"][0]["name"], created["name"])

		self.assertEqual(delete_campaign(created["name"]), {"deleted": created["name"]})
		self.assertFalse(frappe.db.exists("CRM Campaign", created["name"]))

	def test_campaign_code_is_server_managed(self):
		created = self._create_campaign(stable_code="CUSTOM-CODE")

		self.assertRegex(created["stable_code"], r"^CAM-\d{4}-\d{5,}$")
		self.assertNotEqual(created["stable_code"], "CUSTOM-CODE")

		with self.assertRaises(frappe.ValidationError):
			update_campaign(created["name"], stable_code="CAM-2026-99999")

		self.assertEqual(get_campaign(name=created["name"])["stable_code"], created["stable_code"])

	def test_lead_sale_can_create_and_update_campaign(self):
		frappe.set_user("leadsale@gmail.com")
		try:
			self.assertTrue(frappe.has_permission("CRM Campaign", "create"))
			self.assertTrue(frappe.has_permission("CRM Campaign", "write"))
		finally:
			frappe.set_user(self._original_user)
