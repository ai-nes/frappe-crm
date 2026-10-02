from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.fcrm.permissions import (
	_has_interaction_create_permission,
	get_interaction_permission_query_conditions,
)


class TestInteractionCreatePermissions(TestCase):
	def test_full_student_read_scope_applies_to_interaction_reads_only(self):
		with (
			patch("crm.fcrm.permissions.can_read_full_lead_board", return_value=True),
			patch("crm.fcrm.permissions.get_permission_query_conditions", return_value="1=0"),
		):
			self.assertIsNone(
				get_interaction_permission_query_conditions(user="qa", doctype="CRM Interaction")
			)
			self.assertEqual(
				get_interaction_permission_query_conditions(
					user="qa", doctype="CRM Interaction", for_owner_scope=True
				),
				"1=0",
			)

	def test_create_follows_effective_student_read_permission(self):
		student = frappe._dict(doctype="CRM Student", name="STU-1")
		interaction = frappe._dict(student="STU-1")
		for allowed in (True, False):
			with (
				self.subTest(allowed=allowed),
				patch("crm.fcrm.permissions.frappe.db.exists", return_value="STU-1"),
				patch("crm.fcrm.permissions.frappe.get_doc", return_value=student),
				patch("crm.fcrm.permissions.frappe.has_permission", return_value=allowed) as permission,
			):
				self.assertEqual(_has_interaction_create_permission(interaction, user="qa"), allowed)
				permission.assert_called_once_with("CRM Student", ptype="read", doc=student, user="qa")

	def test_create_rejects_missing_or_nonexistent_target(self):
		self.assertFalse(_has_interaction_create_permission(frappe._dict()))
		with patch("crm.fcrm.permissions.frappe.db.exists", return_value=None):
			self.assertFalse(_has_interaction_create_permission(frappe._dict(student="missing")))
