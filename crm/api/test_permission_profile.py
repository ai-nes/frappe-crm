from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.permission_profile import list_permission_profiles, update_permission_profile
from crm.fcrm.permission_groups import permission_group_for_doctype


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

	def _group_key(self, document_type):
		group = permission_group_for_doctype(document_type)
		return group["document_type"] if group else document_type

	def _original_group_keys(self):
		return list(
			dict.fromkeys(
				self._group_key(row["document_type"])
				for row in self.original["applicable_doctypes"]
				if permission_group_for_doctype(row["document_type"])
			)
		)

	def test_list_returns_active_profiles_and_matrix_flags(self):
		result = list_permission_profiles(role=self.role, start=0, page_length=1)
		profiles = {profile["role"]: profile for profile in result["profiles"]}

		self.assertIn("Sale", profiles)
		self.assertIn("applicable_doctypes", profiles["Sale"])
		self.assertIn("read", profiles["Sale"]["applicable_doctypes"][0])
		self.assertEqual(result["selected_role"], self.role)
		self.assertEqual(result["total"], len(self._original_group_keys()))
		self.assertEqual(result["start"], 0)
		self.assertEqual(result["page_length"], 1)
		self.assertEqual(len(profiles["Sale"]["applicable_doctypes"]), 1)
		for profile in result["profiles"]:
			doctypes = [row["document_type"] for row in profile["applicable_doctypes"]]
			self.assertEqual(len(doctypes), len(set(doctypes)))

	def test_list_paginates_the_selected_profile_matrix(self):
		page_size = 2
		result = list_permission_profiles(role=self.role, start=page_size, page_length=page_size)

		self.assertEqual(result["total"], len(self._original_group_keys()))
		self.assertEqual(result["start"], page_size)
		self.assertEqual(result["page_length"], page_size)
		sale = next(profile for profile in result["profiles"] if profile["role"] == self.role)
		full_result = list_permission_profiles(role=self.role, start=0, page_length=100)
		full_sale = next(profile for profile in full_result["profiles"] if profile["role"] == self.role)
		self.assertEqual(
			[s["document_type"] for s in sale["applicable_doctypes"]],
			[row["document_type"] for row in full_sale["applicable_doctypes"][page_size : page_size * 2]],
		)

	def test_list_detailed_mode_returns_physical_business_doctypes(self):
		result = list_permission_profiles(
			role=self.role,
			start=0,
			page_length=100,
			view_mode="detailed",
		)
		sale = next(profile for profile in result["profiles"] if profile["role"] == self.role)
		doctypes = [row["document_type"] for row in sale["applicable_doctypes"]]
		expected_doctypes = [
			row["document_type"]
			for row in self.original["applicable_doctypes"]
			if permission_group_for_doctype(row["document_type"])
		]

		self.assertEqual(result["view_mode"], "detailed")
		self.assertEqual(result["total"], len(expected_doctypes))
		self.assertEqual(doctypes, expected_doctypes)
		student_profile = next(
			row
			for row in sale["applicable_doctypes"]
			if row["document_type"] == "CRM Student Admission Profile"
		)
		self.assertEqual(student_profile["group_label"], "Học sinh")

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
		expected_group = self._group_key(rows[0]["document_type"])
		saved_row = next(
			row for row in result["applicable_doctypes"] if row["document_type"] == expected_group
		)
		self.assertTrue(saved_row["read"])
		self.assertFalse(saved_row["write"])
		self.assertFalse(saved_row["create"])
		self.assertFalse(saved_row["delete"])
		self.assertFalse(saved_row["export"])
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

		self.assertEqual(len(result["applicable_doctypes"]), len(self._original_group_keys()))
		result_by_doctype = {item["document_type"]: item for item in result["applicable_doctypes"]}
		updated_group = result_by_doctype[self._group_key(row["document_type"])]
		self.assertEqual(updated_group["write"], updated_row["write"])

	def test_student_group_updates_linked_profile_and_document_rows(self):
		rows = [
			{
				"document_type": "CRM Student",
				"read": True,
				"write": True,
				"create": True,
				"delete": False,
				"export": True,
			}
		]
		with patch("crm.patches.v1_0.setup_crm_permissions.apply_managed_docperms"):
			update_permission_profile(
				role=self.role,
				row_scope=self.original["row_scope"],
				delete_requires_ownership=self.original["delete_requires_ownership"],
				applicable_doctypes=rows,
			)

		stored = frappe.get_doc("CRM Permission Profile", self.profile_name)
		flags_by_doctype = {
			row.document_type: {
				field: bool(row.get(field)) for field in ("read", "write", "create", "delete", "export")
			}
			for row in stored.applicable_doctypes
		}
		for document_type in ("CRM Student", "CRM Student Admission Profile", "CRM Student Document"):
			self.assertEqual(
				flags_by_doctype[document_type],
				{
					"read": True,
					"write": True,
					"create": True,
					"delete": False,
					"export": True,
				},
			)

	def test_detailed_update_changes_only_selected_doctype(self):
		rows = [
			{
				"document_type": "CRM Student Admission Profile",
				"read": True,
				"write": False,
				"create": False,
				"delete": False,
				"export": False,
			}
		]
		with patch("crm.patches.v1_0.setup_crm_permissions.apply_managed_docperms"):
			result = update_permission_profile(
				role=self.role,
				row_scope=self.original["row_scope"],
				delete_requires_ownership=self.original["delete_requires_ownership"],
				applicable_doctypes=rows,
				replace_applicable_doctypes=False,
				view_mode="detailed",
			)

		stored = frappe.get_doc("CRM Permission Profile", self.profile_name)
		flags_by_doctype = {
			row.document_type: {
				field: bool(row.get(field)) for field in ("read", "write", "create", "delete", "export")
			}
			for row in stored.applicable_doctypes
		}
		self.assertTrue(flags_by_doctype["CRM Student"]["write"])
		self.assertFalse(flags_by_doctype["CRM Student Admission Profile"]["write"])
		self.assertTrue(flags_by_doctype["CRM Student Document"]["write"])
		self.assertEqual(result["view_mode"], "detailed")

	def test_non_business_doctype_rows_are_hidden_and_preserved(self):
		profile = frappe.get_doc("CRM Permission Profile", self.profile_name)
		for document_type in ("Fields Layout", "User"):
			profile.append(
				"applicable_doctypes",
				{
					"document_type": document_type,
					"read": True,
					"write": True,
					"create": False,
					"delete": False,
					"export": False,
				},
			)
		profile.save(ignore_permissions=True)

		for view_mode in ("grouped", "detailed"):
			listed = list_permission_profiles(
				role=self.role,
				start=0,
				page_length=100,
				view_mode=view_mode,
			)
			visible_doctypes = [
				row["document_type"] for item in listed["profiles"] for row in item["applicable_doctypes"]
			]
			for document_type in ("Fields Layout", "User"):
				self.assertNotIn(document_type, visible_doctypes)

		with patch("crm.patches.v1_0.setup_crm_permissions.apply_managed_docperms"):
			result = update_permission_profile(
				role=self.role,
				row_scope=self.original["row_scope"],
				delete_requires_ownership=self.original["delete_requires_ownership"],
				applicable_doctypes=[
					{
						"document_type": "CRM Student",
						"read": True,
						"write": True,
						"create": False,
						"delete": False,
						"export": False,
					}
				],
			)

		result_doctypes = [row["document_type"] for row in result["applicable_doctypes"]]
		self.assertNotIn("Fields Layout", result_doctypes)
		self.assertNotIn("User", result_doctypes)
		stored = frappe.get_doc("CRM Permission Profile", self.profile_name)
		for document_type in ("Fields Layout", "User"):
			hidden_row = next(row for row in stored.applicable_doctypes if row.document_type == document_type)
			self.assertTrue(hidden_row.read)
			self.assertTrue(hidden_row.write)

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
