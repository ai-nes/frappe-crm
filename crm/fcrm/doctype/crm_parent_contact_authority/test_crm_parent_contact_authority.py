from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_parent_context import revoke_parent_contact_authority


class TestCRMParentContactAuthority(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_parent_authority_is_command_only(self):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Parent Contact Authority",
				"student": "__missing_student__",
				"contact": "__missing_contact__",
				"relationship_verified": 1,
				"relationship_type": "Parent",
				"lawful_basis": "consent",
				"allowed_channels": ["phone"],
				"effective_at": frappe.utils.now_datetime(),
				"proof_reference": "test-proof",
			}
		)
		doc.flags.ignore_links = True
		with self.assertRaises(frappe.PermissionError):
			doc.insert(ignore_permissions=True)

	def test_parent_authority_revoke_requires_reviewer_role_before_loading_record(self):
		frappe.set_user("sales@example.com")
		try:
			with patch("frappe.get_roles", return_value=["Sales User"]):
				with self.assertRaises(frappe.PermissionError):
					revoke_parent_contact_authority("AUTH-OUT-OF-SCOPE", evidence="ticket-1")
		finally:
			frappe.set_user("Administrator")

	def test_parent_authority_revoke_uses_reviewer_and_contact_scope(self):
		parent = SimpleNamespace(
			name="AUTH-1",
			student="STU-1",
			contact="CON-1",
			revoked_at=None,
			revocation_evidence=None,
			save=Mock(),
		)
		student = SimpleNamespace(name="STU-1", has_permission=Mock(return_value=True))
		captured_at = datetime(2026, 8, 30, tzinfo=timezone.utc)
		with (
			patch("frappe.get_doc", side_effect=[parent, student]),
			patch("frappe.has_permission", return_value=True),
			patch("crm.fcrm.student_parent_context.now_datetime", return_value=captured_at),
			patch("crm.fcrm.student_parent_context.mark_student_context_changed"),
		):
			result = revoke_parent_contact_authority("AUTH-1", evidence="ticket-1")

		self.assertEqual(result["status"], "revoked")
		self.assertEqual(parent.revocation_evidence, "ticket-1")
		parent.save.assert_called_once_with(ignore_permissions=True)
