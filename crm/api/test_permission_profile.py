from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.permission_profile import list_permission_profiles, update_permission_profile


class TestPermissionProfileApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.role = "Sale"
		self.profile_name = frappe.db.get_value("CRM Permission Profile", {"role": self.role}, "name")
		self.assertTrue(self.profile_name)
		self.profile = frappe.get_doc("CRM Permission Profile", self.profile_name)
		self.original = {
			"row_scope": self.profile.row_scope,
			"delete_requires_ownership": self.profile.delete_requires_ownership,
			"applicable_doctypes": [
				{
					"document_type": row.document_type,
					"read": row.read,
					"write": row.write,
					"create": row.create,
					"delete": row.delete,
					"export": row.export,
				}
				for row in self.profile.applicable_doctypes
			],
		}

	def tearDown(self):
		frappe.set_user("Administrator")
		profile = frappe.get_doc("CRM Permission Profile", self.profile_name)
		profile.row_scope = self.original["row_scope"]
		profile.delete_requires_ownership = self.original["delete_requires_ownership"]
		profile.set("applicable_doctypes", [])
		for row in self.original["applicable_doctypes"]:
			profile.append("applicable_doctypes", row)
		profile.save(ignore_permissions=True)

	def test_list_returns_active_profiles_and_matrix_flags(self):
		result = list_permission_profiles(role=self.role, start=0, page_length=1)
		profiles = {profile["role"]: profile for profile in result["profiles"]}

		self.assertIn("Sale", profiles)
		self.assertIn("applicable_doctypes", profiles["Sale"])
		self.assertIn("read", profiles["Sale"]["applicable_doctypes"][0])
		self.assertEqual(result["selected_role"], self.role)
		self.assertEqual(result["total"], len(self.original["applicable_doctypes"]))
		self.assertEqual(result["start"], 0)
		self.assertEqual(result["page_length"], 1)
		self.assertEqual(len(profiles["Sale"]["applicable_doctypes"]), 1)
		for profile in result["profiles"]:
			doctypes = [row["document_type"] for row in profile["applicable_doctypes"]]
			self.assertEqual(len(doctypes), len(set(doctypes)))

	def test_list_paginates_the_selected_profile_matrix(self):
		page_size = 2
		result = list_permission_profiles(role=self.role, start=page_size, page_length=page_size)

		self.assertEqual(result["total"], len(self.original["applicable_doctypes"]))
		self.assertEqual(result["start"], page_size)
		self.assertEqual(result["page_length"], page_size)
		sale = next(profile for profile in result["profiles"] if profile["role"] == self.role)
		self.assertEqual(
			[s["document_type"] for s in sale["applicable_doctypes"]],
			[row["document_type"] for row in self.original["applicable_doctypes"][page_size : page_size * 2]],
		)

	def test_update_validates_and_syncs_managed_docperms(self):
		rows = [
			{
				"document_type": self.original["applicable_doctypes"][0]["document_type"],
				"read": True,
				"write": False,
				"create": False,
				"delete": False,
				"export": False,
			}
		]
		with patch("crm.patches.v1_0.setup_crm_permissions.apply_managed_docperms") as sync:
			result = update_permission_profile(
				role=self.role,
				row_scope="assigned",
				delete_requires_ownership=True,
				applicable_doctypes=rows,
			)

		self.assertEqual(result["role"], self.role)
		self.assertTrue(result["delete_requires_ownership"])
		self.assertEqual(
			result["applicable_doctypes"],
			[
				{
					"document_type": rows[0]["document_type"],
					"read": True,
					"write": False,
					"create": False,
					"delete": False,
					"export": False,
				}
			],
		)
		sync.assert_called_once_with()

	def test_update_rejects_duplicate_doctypes(self):
		doctype = self.original["applicable_doctypes"][0]["document_type"]
		rows = [{"document_type": doctype}, {"document_type": doctype}]
		with self.assertRaises(frappe.ValidationError):
			update_permission_profile(
				role=self.role,
				row_scope="assigned",
				applicable_doctypes=rows,
			)

	def test_partial_update_preserves_rows_from_other_pages(self):
		row = self.original["applicable_doctypes"][0]
		updated_row = {**row, "write": not bool(row["write"])}
		with patch("crm.patches.v1_0.setup_crm_permissions.apply_managed_docperms"):
			result = update_permission_profile(
				role=self.role,
				row_scope=self.original["row_scope"],
				delete_requires_ownership=self.original["delete_requires_ownership"],
				applicable_doctypes=[updated_row],
				replace_applicable_doctypes=False,
			)

		self.assertEqual(len(result["applicable_doctypes"]), len(self.original["applicable_doctypes"]))
		result_by_doctype = {item["document_type"]: item for item in result["applicable_doctypes"]}
		self.assertEqual(result_by_doctype[row["document_type"]]["write"], updated_row["write"])

	def test_list_is_gated_to_role_managers(self):
		user = "_test_permission_profile_viewer@example.com"
		if frappe.db.exists("User", user):
			frappe.delete_doc("User", user, force=True)
		frappe.get_doc(
			{
				"doctype": "User",
				"email": user,
				"first_name": "Permission Viewer",
				"send_welcome_email": 0,
				"roles": [{"role": "Sale"}],
			}
		).insert(ignore_permissions=True)
		try:
			frappe.set_user(user)
			with self.assertRaises(frappe.PermissionError):
				list_permission_profiles()
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("User", user, force=True)
