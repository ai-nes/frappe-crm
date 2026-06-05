# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMMajor(FrappeTestCase):
	def test_create_major(self):
		major = frappe.get_doc(
			{
				"doctype": "CRM Major",
				"major_name": "_Test Major",
				"major_code": "T99",
				"is_active": 1,
			}
		)
		major.insert(ignore_permissions=True)
		self.assertEqual(major.major_name, "_Test Major")
		major.delete()
