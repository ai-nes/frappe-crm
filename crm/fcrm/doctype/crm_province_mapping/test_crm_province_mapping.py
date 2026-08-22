# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.exceptions import DuplicateEntryError, LinkValidationError, MandatoryError, ValidationError
from frappe.tests.utils import FrappeTestCase


class TestCRMProvinceMapping(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("CRM Province", "_Test Old Province"):
			frappe.get_doc(
				{
					"doctype": "CRM Province",
					"province_code": "_TESTOLD",
					"province_name": "_Test Old Province",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Province Mapping", filters={"old_province": ["like", "_Test%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Province Mapping", name, force=True)
		if frappe.db.exists("CRM Province", "_Test Old Province"):
			frappe.delete_doc("CRM Province", "_Test Old Province", force=True)

	def _make_mapping(self, old_province="_Test Old Province", new_province="_Test New Province"):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Province Mapping",
				"old_province": old_province,
				"new_province": new_province,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_create_mapping(self):
		doc = self._make_mapping()
		self.assertEqual(doc.name, "_Test Old Province")
		self.assertEqual(doc.new_province, "_Test New Province")

	def test_old_province_required(self):
		# old_province is also the autoname source (autoname: field:old_province),
		# so a blank value fails naming (ValidationError) before mandatory-field
		# validation would otherwise raise MandatoryError.
		doc = frappe.get_doc(
			{
				"doctype": "CRM Province Mapping",
				"new_province": "_Test New Province",
			}
		)
		with self.assertRaises(ValidationError):
			doc.insert(ignore_permissions=True)

	def test_new_province_required(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Province Mapping",
				"old_province": "_Test Old Province",
			}
		)
		with self.assertRaises(MandatoryError):
			doc.insert(ignore_permissions=True)

	def test_old_province_must_be_valid_link(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Province Mapping",
				"old_province": "_Test Nonexistent Province",
				"new_province": "_Test New Province",
			}
		)
		with self.assertRaises(LinkValidationError):
			doc.insert(ignore_permissions=True)

	def test_old_province_unique(self):
		self._make_mapping()
		duplicate = frappe.get_doc(
			{
				"doctype": "CRM Province Mapping",
				"old_province": "_Test Old Province",
				"new_province": "_Test Another New Province",
			}
		)
		with self.assertRaises(DuplicateEntryError):
			duplicate.insert(ignore_permissions=True)
