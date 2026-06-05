# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMWard(FrappeTestCase):
	def test_create_ward(self):
		ward = frappe.get_doc(
			{
				"doctype": "CRM Ward",
				"ward_name": "_Test Ward",
				"ward_type": "Ward",
			}
		)
		ward.insert(ignore_permissions=True)
		self.assertEqual(ward.ward_name, "_Test Ward")
		ward.delete()
