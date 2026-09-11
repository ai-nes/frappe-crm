from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.note import (
	create_lead_note,
	create_note,
	delete_lead_note,
	delete_note,
	get_note,
	list_lead_notes,
	list_notes,
	update_lead_note,
	update_note,
)
from crm.fcrm.student_reference import canonical_student


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

	def test_lead_note_crud_contract(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Lead Note API",
				"phone": "0912345681",
				"email": "lead-note-api@example.com",
			}
		).insert(ignore_permissions=True)

		created = create_lead_note(lead.name, content="Ghi chú Lead")
		self.assertEqual(created["reference_doctype"], "CRM Lead")
		self.assertEqual(list_lead_notes(lead.name)["total"], 1)

		updated = update_lead_note(created["name"], content="Ghi chú Lead đã cập nhật")
		self.assertEqual(updated["content"], "Ghi chú Lead đã cập nhật")
		self.assertEqual(delete_lead_note(created["name"]), {"deleted": created["name"]})

	def test_lead_alias_writes_to_canonical_student(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Canonical Note Student Lead",
				"phone": "0912345682",
				"email": "canonical-note-lead@example.com",
			}
		).insert(ignore_permissions=True)
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Canonical Note Student",
				"email": "canonical-note-student@example.com",
				"source_lead": lead.name,
			}
		).insert(ignore_permissions=True)

		created = create_lead_note(lead.name, content="Ghi chú Student")

		self.assertEqual(created["reference_doctype"], "CRM Student")
		self.assertEqual(created["reference_docname"], student.name)
		self.assertEqual(canonical_student(lead.name), student.name)
		self.assertEqual(list_lead_notes(lead.name)["total"], 1)
		self.assertEqual(update_lead_note(created["name"], content="Đã cập nhật")["content"], "Đã cập nhật")
		self.assertEqual(delete_lead_note(created["name"]), {"deleted": created["name"]})

	def test_lead_alias_resolves_public_lead_id(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Public Lead ID Note",
				"phone": "0912345683",
				"email": "public-lead-id-note@example.com",
			}
		).insert(ignore_permissions=True)

		created = create_lead_note(lead.lead_id, content="Ghi chú theo public Lead ID")
		listed = list_lead_notes(lead.lead_id)

		self.assertEqual(created["reference_doctype"], "CRM Lead")
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["notes"][0]["content"], "Ghi chú theo public Lead ID")

	def test_display_student_reference_is_resolved_at_note_boundary(self):
		student = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"full_name": "Display Reference Student",
				"email": "display-reference@example.com",
				"stage": "Interested",
			}
		).insert(ignore_permissions=True)
		display_code = "HS-2026-HCM-000021"

		with patch("crm.api.note.canonical_student", return_value=student.name):
			created = create_note("CRM Student", display_code, content="Display code note")
			listed = list_notes("CRM Student", display_code)

		self.assertEqual(created["reference_docname"], student.name)
		self.assertEqual(listed["total"], 1)
		self.assertEqual(listed["notes"][0]["reference_docname"], student.name)

	def test_lead_note_crud_contract(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "Lead Note API",
				"phone": "0912345681",
				"email": "lead-note-api@example.com",
			}
		).insert(ignore_permissions=True)

		created = create_lead_note(lead.name, content="Ghi chú Lead")
		self.assertEqual(created["reference_doctype"], "CRM Lead")
		self.assertEqual(list_lead_notes(lead.name)["total"], 1)

		updated = update_lead_note(created["name"], content="Ghi chú Lead đã cập nhật")
		self.assertEqual(updated["content"], "Ghi chú Lead đã cập nhật")
		self.assertEqual(delete_lead_note(created["name"]), {"deleted": created["name"]})
