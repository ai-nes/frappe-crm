# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMBranch(FrappeTestCase):
	def test_create_branch(self):
		branch = frappe.get_doc(
			{
				"doctype": "CRM Branch",
				"branch_name": "_Test Branch",
				"branch_code": "test",
			}
		)
		branch.insert(ignore_permissions=True)
		self.assertEqual(branch.branch_name, "_Test Branch")
		branch.delete()
