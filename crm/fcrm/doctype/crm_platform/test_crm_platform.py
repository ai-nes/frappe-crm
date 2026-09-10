# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.exceptions import DuplicateEntryError, MandatoryError, ValidationError
from frappe.tests.utils import FrappeTestCase


class TestCRMPlatform(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("CRM Lead Source", "_Test Platform Source"):
			frappe.get_doc(
				{
					"doctype": "CRM Lead Source",
					"source_name": "_Test Platform Source",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		for name in frappe.db.get_all("CRM Platform", filters={"platform_name": ["like", "_Test%"]}, pluck="name"):
			frappe.delete_doc("CRM Platform", name, force=True)
		if frappe.db.exists("CRM Lead Source", "_Test Platform Source"):
			frappe.delete_doc("CRM Lead Source", "_Test Platform Source", force=True)

	def _make_platform(self, name="_Test Platform", sub_channel=None, channel_url=None):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Platform",
				"platform_name": name,
				"lead_source": "_Test Platform Source",
			}
		)
		if sub_channel is not None:
			doc.sub_channel = sub_channel
		if channel_url is not None:
			doc.channel_url = channel_url
		doc.insert(ignore_permissions=True)
		return doc

	def test_create_platform(self):
		doc = self._make_platform()
		self.assertEqual(doc.name, "_Test Platform")
		self.assertEqual(doc.lead_source, "_Test Platform Source")

	def test_platform_name_required(self):
		# platform_name is also the autoname source (autoname: field:platform_name),
		# so a blank value fails naming (ValidationError) before mandatory-field
		# validation would otherwise raise MandatoryError.
		doc = frappe.get_doc(
			{
				"doctype": "CRM Platform",
				"lead_source": "_Test Platform Source",
			}
		)
		with self.assertRaises(ValidationError):
			doc.insert(ignore_permissions=True)

	def test_lead_source_required(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Platform",
				"platform_name": "_Test Platform No Source",
			}
		)
		with self.assertRaises(MandatoryError):
			doc.insert(ignore_permissions=True)

	def test_platform_name_unique(self):
		self._make_platform()
		duplicate = frappe.get_doc(
			{
				"doctype": "CRM Platform",
				"platform_name": "_Test Platform",
				"lead_source": "_Test Platform Source",
			}
		)
		with self.assertRaises(DuplicateEntryError):
			duplicate.insert(ignore_permissions=True)

	def test_sub_channel_accepts_valid_options(self):
		doc = self._make_platform("_Test Platform Form", sub_channel="Form")
		self.assertEqual(doc.sub_channel, "Form")

		doc2 = self._make_platform("_Test Platform Landing", sub_channel="Landing Page")
		self.assertEqual(doc2.sub_channel, "Landing Page")

	def test_sub_channel_optional(self):
		doc = self._make_platform("_Test Platform No Sub Channel")
		self.assertIn(doc.sub_channel, (None, ""))

	def test_channel_url_is_stored(self):
		doc = self._make_platform(
			"_Test Platform URL",
			channel_url="https://www.facebook.com/faip.crm",
		)
		self.assertEqual(doc.channel_url, "https://www.facebook.com/faip.crm")
