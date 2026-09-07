import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.note import create_note, delete_note, get_note, list_notes, update_note


class TestNoteApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")
		if not frappe.db.exists("CRM Interaction Type", "NOTE"):
			frappe.get_doc(
				{
					"doctype": "CRM Interaction Type",
					"code": "NOTE",
					"display_name": "Ghi chú tư vấn",
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def test_note_crud_returns_owner_full_name_without_title(self):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Note API Contact",
				"email": "note-api-contact@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		created = create_note("CRM Student", contact.name, content="Initial note")
		owner_full_name = frappe.get_cached_value("User", "Administrator", "full_name")

		self.assertEqual(created["content"], "Initial note")
		self.assertEqual(created["owner_full_name"], owner_full_name)
		self.assertNotIn("title", created)

		listed = list_notes("CRM Student", contact.name)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["notes"][0]["owner_full_name"], owner_full_name)

		fetched = get_note(created["name"])
		self.assertEqual(fetched["owner_full_name"], owner_full_name)

		updated = update_note(created["name"], content="Updated note")
		self.assertEqual(updated["content"], "Updated note")
		self.assertEqual(updated["owner_full_name"], owner_full_name)

		self.assertEqual(delete_note(created["name"]), {"deleted": created["name"]})
		self.assertFalse(frappe.db.exists("FCRM Note", created["name"]))
		interaction = frappe.db.get_value(
			"CRM Interaction",
			{"external_id": f"FCRM Note:{created['name']}:NOTE"},
			["reference_doctype", "reference_docname"],
			as_dict=True,
		)
		self.assertIsNotNone(interaction)
		self.assertIsNone(interaction.reference_doctype)
		self.assertIsNone(interaction.reference_docname)

	def test_note_insert_creates_scoped_internal_interaction(self):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Note Interaction Contact",
				"email": "note-interaction@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		note = create_note("CRM Student", contact.name, content="Tư vấn hồ sơ")
		interaction = frappe.db.get_value(
			"CRM Interaction",
			{"external_id": f"FCRM Note:{note['name']}:NOTE"},
			["name", "crm_contact", "reference_doctype", "reference_docname", "channel", "direction"],
			as_dict=True,
		)

		self.assertIsNotNone(interaction)
		self.assertEqual(interaction.crm_contact, contact.name)
		self.assertEqual(interaction.reference_doctype, "FCRM Note")
		self.assertEqual(interaction.reference_docname, note["name"])
		self.assertEqual(interaction.channel, "Internal")
		self.assertEqual(interaction.direction, "internal")
