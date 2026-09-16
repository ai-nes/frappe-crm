from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import snippets
from crm.fcrm.doctype.crm_snippet import crm_snippet


class TestSnippets(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.original_user = frappe.session.user
		frappe.set_user("Administrator")
		self.created_names = []

	def tearDown(self):
		for name in reversed(self.created_names):
			if frappe.db.exists(snippets.SNIPPET, name):
				frappe.delete_doc(snippets.SNIPPET, name, force=True, ignore_permissions=True)
		frappe.set_user(self.original_user)
		frappe.db.rollback()
		super().tearDown()

	def _create(self, **overrides):
		data = {
			"internalName": "Test greeting snippet",
			"snippetText": "Chào {{student.full_name}}, mình có thể hỗ trợ gì cho bạn?",
			"shortcut": "greeting",
			"sharing": "public",
			**overrides,
		}
		result = snippets.create_snippet(data)
		self.created_names.append(result["id"])
		return result

	def test_crud_returns_ui_contract_and_server_managed_code(self):
		created = self._create()
		self.assertRegex(created["code"], r"^SNP-\d{3}$")
		self.assertEqual(created["sharing"], "public")

		listed = snippets.list_snippets(search="greeting")
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["snippets"][0]["id"], created["id"])

		updated = snippets.update_snippet(
			created["id"],
			{
				"internalName": "Private greeting snippet",
				"snippetText": "Nội dung riêng",
				"shortcut": "private-greeting",
				"sharing": "private",
			},
			expected_modified=created["modifiedAt"],
		)
		self.assertEqual(updated["sharing"], "private")
		self.assertEqual(updated["internalName"], "Private greeting snippet")

		deleted = snippets.delete_snippet(updated["id"], expected_modified=updated["modifiedAt"])
		self.assertTrue(deleted["deleted"])
		self.created_names.remove(created["id"])

	def test_invalid_sharing_and_empty_content_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self._create(sharing="team")
		with self.assertRaises(frappe.ValidationError):
			self._create(snippetText="<p><br></p>")

	def test_list_is_paginated_and_returns_toolbar_metadata(self):
		baseline = snippets.list_snippets(page=1, pageSize=5)
		for index in range(1, 7):
			self._create(
				internalName=f"Paged snippet {index}",
				snippetText=f"Page content {index}",
				shortcut=f"paged-{index}",
			)

		listed = snippets.list_snippets(search="Paged snippet", page=2, pageSize=5)

		self.assertEqual(listed["total"], 6)
		self.assertEqual(listed["totalAll"], baseline["totalAll"] + 6)
		self.assertEqual(listed["totalMine"], baseline["totalMine"] + 6)
		self.assertEqual(listed["page"], 2)
		self.assertEqual(listed["pageSize"], 5)
		self.assertEqual(listed["totalPages"], 2)
		self.assertFalse(listed["hasNextPage"])
		self.assertEqual(len(listed["snippets"]), 1)
		self.assertTrue(any(owner["id"] == "Administrator" for owner in listed["owners"]))

		filtered = snippets.list_snippets(search="paged-6", page=1, pageSize=5)
		self.assertEqual(filtered["total"], 1)
		self.assertEqual(filtered["snippets"][0]["shortcut"], "paged-6")

	def test_row_permissions_keep_private_snippets_owner_only(self):
		private_doc = frappe._dict(owner="owner@example.com", is_public=0)
		public_doc = frappe._dict(owner="owner@example.com", is_public=1)
		with patch.object(snippets.frappe, "get_roles", return_value=[]):
			self.assertTrue(crm_snippet.has_permission(private_doc, "owner@example.com", "read"))
			self.assertFalse(crm_snippet.has_permission(private_doc, "other@example.com", "read"))
			self.assertTrue(crm_snippet.has_permission(public_doc, "other@example.com", "read"))
			self.assertFalse(crm_snippet.has_permission(public_doc, "other@example.com", "write"))
			self.assertFalse(crm_snippet.has_permission(public_doc, "Guest", "read"))

	def test_expected_modified_prevents_lost_update(self):
		created = self._create()
		with self.assertRaises(frappe.ValidationError):
			snippets.update_snippet(
				created["id"],
				{
					"internalName": "Changed",
					"snippetText": "Changed",
					"shortcut": "changed",
					"sharing": "public",
				},
				expected_modified="2000-01-01 00:00:00",
			)
