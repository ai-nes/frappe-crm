from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import message_templates, snippets
from crm.fcrm.doctype.crm_message_template import crm_message_template


class TestMessageTemplates(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self.original_user = frappe.session.user
		frappe.set_user("Administrator")
		self.created_names = []
		self.created_library_names = []
		self.created_snippet_names = []
		self.created_lead_names = []

	def tearDown(self):
		for name in reversed(self.created_names):
			if frappe.db.exists(message_templates.MESSAGE_TEMPLATE, name):
				frappe.delete_doc(
					message_templates.MESSAGE_TEMPLATE,
					name,
					force=True,
					ignore_permissions=True,
				)
		for name in reversed(self.created_library_names):
			if frappe.db.exists(message_templates.MESSAGE_TEMPLATE_LIBRARY, name):
				frappe.delete_doc(
					message_templates.MESSAGE_TEMPLATE_LIBRARY,
					name,
					force=True,
					ignore_permissions=True,
				)
		for name in reversed(self.created_snippet_names):
			if frappe.db.exists(snippets.SNIPPET, name):
				frappe.delete_doc(snippets.SNIPPET, name, force=True, ignore_permissions=True)
		for name in reversed(self.created_lead_names):
			if frappe.db.exists("CRM Lead", name):
				frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)
		frappe.set_user(self.original_user)
		frappe.db.rollback()
		super().tearDown()

	def _create(self, **overrides):
		data = {
			"name": "Test welcome template",
			"subject": "Welcome {{student.first_name}}",
			"body": "<p>Hello {{student.first_name}}</p>",
			"sharing": "public",
			**overrides,
		}
		result = message_templates.create_message_template(data)
		self.created_names.append(result["id"])
		return result

	def test_crud_returns_ui_contract_and_server_managed_code(self):
		created = self._create()
		self.assertRegex(created["code"], r"^MSG-\d{3}$")
		self.assertEqual(created["sharing"], "public")

		listed = message_templates.list_message_templates(search="welcome")
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["templates"][0]["id"], created["id"])

		updated = message_templates.update_message_template(
			created["id"],
			{
				"name": "Private welcome template",
				"subject": "Updated subject",
				"body": "<p>Updated body</p>",
				"sharing": "private",
			},
			expected_modified=created["modifiedAt"],
		)
		self.assertEqual(updated["sharing"], "private")
		self.assertEqual(updated["name"], "Private welcome template")

		deleted = message_templates.delete_message_template(
			created["id"], expected_modified=updated["modifiedAt"]
		)
		self.assertTrue(deleted["deleted"])
		self.created_names.remove(created["id"])

	def test_invalid_sharing_and_empty_body_are_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self._create(sharing="team")
		with self.assertRaises(frappe.ValidationError):
			self._create(body="<p><br></p>")

	def test_row_permissions_keep_private_templates_owner_only(self):
		private_doc = frappe._dict(owner="owner@example.com", is_public=0)
		public_doc = frappe._dict(owner="owner@example.com", is_public=1)
		with patch.object(message_templates.frappe, "get_roles", return_value=[]):
			self.assertTrue(crm_message_template.has_permission(private_doc, "owner@example.com", "read"))
			self.assertFalse(crm_message_template.has_permission(private_doc, "other@example.com", "read"))
			self.assertTrue(crm_message_template.has_permission(public_doc, "other@example.com", "read"))
			self.assertFalse(crm_message_template.has_permission(public_doc, "other@example.com", "write"))

	def test_expected_modified_prevents_lost_update(self):
		created = self._create()
		with self.assertRaises(frappe.ValidationError):
			message_templates.update_message_template(
				created["id"],
				{
					"name": "Changed",
					"subject": "Changed",
					"body": "<p>Changed</p>",
					"sharing": "public",
				},
				expected_modified="2000-01-01 00:00:00",
			)

	def test_library_returns_only_system_templates(self):
		regular = self._create(name="Test regular template")
		doc = frappe.get_doc(
			{
				"doctype": message_templates.MESSAGE_TEMPLATE_LIBRARY,
				"naming_series": "MSG-LIB-.###",
				"owner": "Administrator",
				"template_name": "Test system library template",
				"category": "test",
				"description": "Test library description",
				"subject": "Test subject",
				"body": "Test body",
			}
		).insert(ignore_permissions=True)
		self.created_library_names.append(doc.name)

		result = message_templates.list_message_template_library()
		template = next(item for item in result["templates"] if item["id"] == doc.name)
		self.assertEqual(template["description"], "Test library description")
		self.assertEqual(template["libraryCategory"], "test")
		self.assertTrue(template["isSystemTemplate"])
		self.assertNotIn(regular["id"], {item["id"] for item in result["templates"]})
		admin_result = message_templates.list_admin_message_template_library()
		self.assertIn(doc.name, {item["id"] for item in admin_result["templates"]})
		main_list = message_templates.list_message_templates()
		self.assertNotIn(doc.name, {item["id"] for item in main_list["templates"]})

	def test_admin_can_crud_library_templates(self):
		created = message_templates.create_message_template_library(
			{
				"name": "Admin library template",
				"subject": "Library subject",
				"body": "Library body",
			}
		)
		self.created_library_names.append(created["id"])
		self.assertRegex(created["code"], r"^MSG-LIB-\d{3}$")

		updated = message_templates.update_message_template_library(
			created["id"],
			{"name": "Updated library template", "subject": "Updated subject", "body": "Updated body"},
			expected_modified=created["modifiedAt"],
		)
		self.assertEqual(updated["name"], "Updated library template")

		deleted = message_templates.delete_message_template_library(
			created["id"], expected_modified=updated["modifiedAt"]
		)
		self.assertTrue(deleted["deleted"])
		self.created_library_names.remove(created["id"])

	def test_preview_resolves_real_lead_tokens_without_mutating_template(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Nguyễn Minh Anh",
				"phone": "0981000042",
				"email": "minhanh@example.com",
				"processing_status": "NEW",
				"resolution": "PENDING",
			}
		)
		frappe.flags.student_intake_service = True
		try:
			lead.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = False
		self.created_lead_names.append(lead.name)

		contacts = message_templates.list_message_template_preview_contacts(search="Minh Anh")
		self.assertIn(lead.name, {contact["id"] for contact in contacts["contacts"]})

		preview = message_templates.preview_message_template(
			lead.name,
			{
				"subject": "Chào {{student.first_name}}",
				"body": "<p>{{student.full_name}} - {{student.email}} - {{student.phone}}</p>",
			},
		)
		self.assertEqual(preview["subject"], "Chào Anh")
		self.assertIn("Nguyễn Minh Anh", preview["body"])
		self.assertIn("minhanh@example.com", preview["body"])
		self.assertNotIn("{{student.", preview["body"])

	def test_preview_expands_visible_snippets_and_reports_missing_references(self):
		snippet = snippets.create_snippet(
			{
				"name": "123",
				"content": "<p>Xin chào {{student.first_name}}</p>",
				"sharing": "private",
			}
		)
		self.created_snippet_names.append(snippet["id"])
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Nguyễn Minh Anh",
				"processing_status": "NEW",
				"resolution": "PENDING",
			}
		)
		frappe.flags.student_intake_service = True
		try:
			lead.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = False
		self.created_lead_names.append(lead.name)

		preview = message_templates.preview_message_template(
			lead.name,
			{
				"subject": "Chào bạn",
				"body": "<div>#123 #(Missing preview snippet)</div>",
			},
		)
		self.assertIn("Xin chào Anh", preview["body"])
		self.assertIn("#(Missing preview snippet)", preview["body"])
		self.assertIn("#(Missing preview snippet)", preview["missingTokens"])
