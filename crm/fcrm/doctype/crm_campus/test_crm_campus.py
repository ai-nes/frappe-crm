# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCampus(FrappeTestCase):
	def test_create_campus(self):
		campus = frappe.get_doc(
			{
				"doctype": "CRM Campus",
				"campus_name": "_Test Campus",
				"campus_code": "test",
			}
		)
		campus.insert(ignore_permissions=True)
		self.assertEqual(campus.campus_name, "_Test Campus")
		campus.delete()
