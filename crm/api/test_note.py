import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.note import create_note, delete_note, get_note, list_notes, update_note


class TestNoteApi(FrappeTestCase):
	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user(self._original_user)
		frappe.db.rollback()

	def test_note_crud_returns_owner_full_name_without_title(self):
		contact = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"full_name": "Note API Contact",
				"email": "note-api-contact@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)

		created = create_note("CRM Contact", contact.name, content="Initial note")
		owner_full_name = frappe.get_cached_value("User", "Administrator", "full_name")

		self.assertEqual(created["content"], "Initial note")
		self.assertEqual(created["owner_full_name"], owner_full_name)
		self.assertNotIn("title", created)

		listed = list_notes("CRM Contact", contact.name)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["notes"][0]["owner_full_name"], owner_full_name)

		fetched = get_note(created["name"])
		self.assertEqual(fetched["owner_full_name"], owner_full_name)

		updated = update_note(created["name"], content="Updated note")
		self.assertEqual(updated["content"], "Updated note")
		self.assertEqual(updated["owner_full_name"], owner_full_name)

		self.assertEqual(delete_note(created["name"]), {"deleted": created["name"]})
		self.assertFalse(frappe.db.exists("FCRM Note", created["name"]))
