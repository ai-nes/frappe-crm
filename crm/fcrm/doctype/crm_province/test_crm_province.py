# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMProvince(FrappeTestCase):
	def test_create_province(self):
		province = frappe.get_doc(
			{
				"doctype": "CRM Province",
				"province_name": "_Test Province",
				"province_code": "_TP",
				"city_type": "Province",
			}
		)
		province.insert(ignore_permissions=True)
		self.assertEqual(province.province_name, "_Test Province")
		province.delete()
