"""Admissions permission contract coverage for Sale and Lead Sales screens.

These checks complement the browser role journeys: the backend remains the
authority even when a control is hidden in the SPA.
"""

import unittest

try:
	import frappe
	from frappe.tests.utils import FrappeTestCase
except ImportError:  # pragma: no cover - bench-only contract module
	frappe = None
	FrappeTestCase = unittest.TestCase

from crm.fcrm.role_policy import capabilities_for_roles


class TestLeadProcessingPermissionContracts(FrappeTestCase):
	def test_sale_can_work_assigned_student_but_not_manage_ownership(self):
		capabilities = capabilities_for_roles({"Sale"})
		self.assertIn("student.engagement.write", capabilities)
		self.assertNotIn("student.ownership.manage", capabilities)

	def test_lead_sales_can_read_scope_but_assignment_is_not_a_phase_two_capability(self):
		capabilities = capabilities_for_roles({"Lead Sales"})
		self.assertIn("student.context.read", capabilities)
		self.assertNotIn("student.ownership.manage", capabilities)

	def test_marketing_does_not_receive_sales_mutations(self):
		capabilities = capabilities_for_roles({"Marketing"})
		self.assertNotIn("student.engagement.write", capabilities)
		self.assertNotIn("student.lifecycle.write", capabilities)

	def test_unknown_or_legacy_sales_role_fails_closed(self):
		self.assertNotIn("student.engagement.write", capabilities_for_roles({"Sales"}))
		self.assertNotIn("student.lifecycle.write", capabilities_for_roles({"Sales"}))


if __name__ == "__main__":  # pragma: no cover
	unittest.main()
