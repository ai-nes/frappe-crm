# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMCampaignTouchpoint(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.campus = self._make_campus("_Test CTP Campus")
		self.campaign = self._make_campaign("_Test CTP Campaign", self.campus)
		self.contact = self._make_contact("_Test CTP Contact", "0977000002")

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Interaction", filters={"reference_doctype": "CRM Campaign Touchpoint"}, pluck="name"
		):
			frappe.delete_doc("CRM Interaction", name, force=True)
		for name in frappe.db.get_all(
			"CRM Campaign Touchpoint", filters={"crm_campaign": self.campaign}, pluck="name"
		):
			frappe.delete_doc("CRM Campaign Touchpoint", name, force=True)
		for name in frappe.db.get_all("CRM Contact", filters={"full_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Contact", name, force=True)
		for name in frappe.db.get_all("CRM Campaign", filters={"title": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campaign", name, force=True)
		for name in frappe.db.get_all("CRM Campus", filters={"campus_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Campus", name, force=True)

	def _make_campus(self, name):
		if frappe.db.exists("CRM Campus", name):
			frappe.delete_doc("CRM Campus", name, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campus", "campus_name": name})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_campaign(self, title, campus):
		if frappe.db.exists("CRM Campaign", title):
			frappe.delete_doc("CRM Campaign", title, force=True)
		doc = frappe.get_doc({"doctype": "CRM Campaign", "title": title, "campus": campus})
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_contact(self, name, phone):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"full_name": name,
				"phone": phone,
				"enrollment_status": "Có triển vọng",
			}
		)
		contact.insert(ignore_permissions=True)
		return contact.name

	def _make_touchpoint(self, **kwargs):
		payload = {
			"doctype": "CRM Campaign Touchpoint",
			"crm_campaign": self.campaign,
			"crm_contact": self.contact,
		}
		payload.update(kwargs)
		return frappe.get_doc(payload)

	# --------------------------------------------------------------- defaults

	def test_before_validate_defaults_student_and_touched_at(self):
		touchpoint = self._make_touchpoint()
		touchpoint.insert(ignore_permissions=True)
		touchpoint.reload()

		expected_student = frappe.db.get_value("CRM Contact", self.contact, "student")
		self.assertEqual(touchpoint.student, expected_student)
		self.assertTrue(touchpoint.touched_at)

	def test_explicit_touched_at_is_not_overridden(self):
		touchpoint = self._make_touchpoint(touched_at="2026-02-01 08:00:00")
		touchpoint.insert(ignore_permissions=True)
		touchpoint.reload()
		self.assertEqual(str(touchpoint.touched_at), "2026-02-01 08:00:00")

	def test_default_source_is_manual(self):
		touchpoint = self._make_touchpoint()
		touchpoint.insert(ignore_permissions=True)
		self.assertEqual(touchpoint.source, "Manual")

	# ---------------------------------------------------------- duplicate guard

	def test_duplicate_campaign_contact_pair_raises(self):
		first = self._make_touchpoint()
		first.insert(ignore_permissions=True)

		duplicate = self._make_touchpoint()
		with self.assertRaises(frappe.ValidationError):
			duplicate.insert(ignore_permissions=True)

	def test_same_contact_different_campaign_is_allowed(self):
		first = self._make_touchpoint()
		first.insert(ignore_permissions=True)

		other_campaign = self._make_campaign("_Test CTP Other Campaign", self.campus)
		second = self._make_touchpoint(crm_campaign=other_campaign)
		second.insert(ignore_permissions=True)  # must not raise
		self.assertTrue(second.name)

	# ---------------------------------------------- Phase 6: interaction dispatch

	def _ensure_interaction_type(self, name):
		if not frappe.db.exists("CRM Interaction Type", name):
			frappe.get_doc(
				{"doctype": "CRM Interaction Type", "interaction_type_name": name}
			).insert(ignore_permissions=True)

	def test_insert_creates_campaign_touched_interaction(self):
		self._ensure_interaction_type("Campaign Touched")
		touchpoint = self._make_touchpoint()
		touchpoint.insert(ignore_permissions=True)

		interaction_name = frappe.db.get_value(
			"CRM Interaction",
			{"reference_doctype": "CRM Campaign Touchpoint", "reference_docname": touchpoint.name},
			"name",
		)
		self.assertTrue(interaction_name)

		interaction = frappe.get_doc("CRM Interaction", interaction_name)
		self.assertEqual(interaction.interaction_type, "Campaign Touched")
		self.assertEqual(interaction.crm_contact, self.contact)

		frappe.delete_doc("CRM Interaction", interaction_name, force=True)

	def test_in_patch_flag_suppresses_campaign_touchpoint_interaction(self):
		self._ensure_interaction_type("Campaign Touched")
		touchpoint = self._make_touchpoint()

		frappe.flags.in_patch = True
		try:
			touchpoint.insert(ignore_permissions=True)
		finally:
			frappe.flags.in_patch = False

		exists = frappe.db.exists(
			"CRM Interaction",
			{"reference_doctype": "CRM Campaign Touchpoint", "reference_docname": touchpoint.name},
		)
		self.assertFalse(exists)
