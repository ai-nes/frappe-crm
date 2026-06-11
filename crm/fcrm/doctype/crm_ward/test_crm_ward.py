# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMWard(FrappeTestCase):
	def test_create_ward(self):
		province = frappe.get_doc(
			{
				"doctype": "CRM Province",
				"province_name": "_Test Ward Province",
				"province_code": "_TWP",
				"city_type": "Province",
			}
		)
		province.insert(ignore_permissions=True)

		ward = frappe.get_doc(
			{
				"doctype": "CRM Ward",
				"ward_code": "_TW",
				"ward_name": "_Test Ward",
				"province": province.name,
				"ward_type": "Ward",
			}
		)
		ward.insert(ignore_permissions=True)
		self.assertEqual(ward.ward_name, "_Test Ward")
		ward.delete()
		province.delete()
