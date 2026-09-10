import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import invite_by_email
from crm.fcrm.doctype.invitation.invitation import Invitation


class TestInvitationRoleContract(FrappeTestCase):
	def test_before_insert_rejects_raw_aliases(self):
		invitation = frappe.get_doc(
			{"doctype": "Invitation", "email": "phase2-alias@example.com", "role": "Sales User"}
		)
		with self.assertRaises(frappe.ValidationError):
			invitation.before_insert()

	def test_before_insert_accepts_canonical_role(self):
		invitation = frappe.get_doc(
			{"doctype": "Invitation", "email": "phase2-canonical@example.com", "role": "Sale"}
		)
		invitation.before_insert()
		self.assertEqual(invitation.status, "Pending")
		self.assertTrue(invitation.key)

	def test_doctype_options_advertise_only_canonical_invitation_roles(self):
		path = Path(__file__).parents[1] / "fcrm" / "doctype" / "invitation" / "invitation.json"
		doctype = json.loads(path.read_text(encoding="utf-8"))
		role_field = next(field for field in doctype["fields"] if field["fieldname"] == "role")
		self.assertEqual(
			set(role_field["options"].splitlines()) - {""},
			{"Sale", "Marketing", "Lead Sale", "Admissions Director", "System Manager"},
		)

	def test_accept_rejects_legacy_pending_invitation_before_creating_a_user(self):
		invitation = frappe.get_doc(
			{"doctype": "Invitation", "email": "phase2-pending-alias@example.com", "role": "Sales User", "status": "Pending"}
		)
		with self.assertRaises(frappe.ValidationError):
			invitation.accept()
		self.assertFalse(frappe.db.exists("User", invitation.email))

	def test_accept_rejects_an_already_accepted_invitation(self):
		invitation = frappe.get_doc(
			{
				"doctype": "Invitation",
				"email": "phase2-replayed@example.com",
				"role": "Sale",
				"status": "Accepted",
			}
		)
		with self.assertRaises(frappe.ValidationError):
			invitation.accept()
		self.assertFalse(frappe.db.exists("User", invitation.email))

	def test_public_invitation_api_rejects_raw_alias(self):
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.PermissionError):
			invite_by_email("phase2-api-alias@example.com", "Sales User")
