# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests.utils import FrappeTestCase


class TestCRMPermissionProfile(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _make_profile(self, role="_Test Permission Profile Role", **kwargs):
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Permission Profile",
				"role": role,
				"row_scope": "assigned",
				"applicable_doctypes": [
					{"document_type": "CRM Student", "read": 1, "write": 1},
					{"document_type": "CRM Contact", "read": 1},
				],
				**kwargs,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc

	def test_saves_and_loads_with_applicable_doctype_rows(self):
		doc = self._make_profile()
		reloaded = frappe.get_doc("CRM Permission Profile", doc.name)
		self.assertEqual(len(reloaded.applicable_doctypes), 2)
		self.assertEqual(reloaded.row_scope, "assigned")

	def test_requires_at_least_one_applicable_doctype_row(self):
		if not frappe.db.exists("Role", "_Test Permission Profile Empty Role"):
			frappe.get_doc({"doctype": "Role", "role_name": "_Test Permission Profile Empty Role"}).insert(
				ignore_permissions=True
			)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Permission Profile",
				"role": "_Test Permission Profile Empty Role",
				"row_scope": "deny",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			doc.insert(ignore_permissions=True)

	def test_role_cannot_be_changed_after_creation(self):
		doc = self._make_profile()
		other_role = "_Test Permission Profile Other Role"
		if not frappe.db.exists("Role", other_role):
			frappe.get_doc({"doctype": "Role", "role_name": other_role}).insert(ignore_permissions=True)
		doc.role = other_role
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
