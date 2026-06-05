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
				"city_type": "Province",
				"city_number": "99",
			}
		)
		province.insert(ignore_permissions=True)
		self.assertEqual(province.province_name, "_Test Province")
		province.delete()
