"""Focused contract tests for the Phase 3 ownership command adapter."""

import inspect
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_ownership import change_student_ownership
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_ownership import (
	StudentOwnershipError,
	_length_delimited,
	ownership_command_keys,
)


class TestStudentOwnershipContract(FrappeTestCase):
	def test_only_lead_sales_and_admissions_director_receive_capability(self):
		self.assertIn("student.ownership.manage", capabilities_for_roles({"Lead Sales"}))
		self.assertIn("student.ownership.manage", capabilities_for_roles({"Admissions Director"}))
		for roles in ({"Sale"}, {"Marketing"}, {"System Manager"}, {"Team Leader"}, {"Sales Manager"}):
			self.assertNotIn("student.ownership.manage", capabilities_for_roles(roles))

	def test_receipt_encoding_is_length_delimited_and_domain_separated(self):
		first = _length_delimited("crm.receipt.command.v1", "ownership", "a", "bc")
		second = _length_delimited("crm.receipt.command.v1", "ownership", "ab", "c")
		self.assertNotEqual(first, second)
		self.assertTrue(first.startswith(b"crm.receipt.command.v1"))

	def test_receipt_keys_use_configured_secret(self):
		with patch.object(frappe, "conf", {"crm_receipt_hmac_secret": "_test_secret"}):
			keys = ownership_command_keys("_test_user@example.com", "_test_ownership_key")
		self.assertEqual(len(keys), 1)
		self.assertEqual(len(keys[0]), 64)

	def test_service_denies_guest_before_schema_access(self):
		frappe.set_user("Guest")
		try:
			with self.assertRaises(StudentOwnershipError) as error:
				from crm.fcrm.student_ownership import change_student_ownership

				change_student_ownership(
					"_test_student",
					"pool",
					"_test_team",
					"_test_team",
					"_test reason",
					"_test key",
					"0",
					"_test correlation",
				)
			self.assertEqual(error.exception.code, "UNAUTHORIZED")
		finally:
			frappe.set_user("Administrator")


class TestStudentOwnershipAPI(FrappeTestCase):
	def test_api_does_not_accept_actor_or_scope_parameters(self):
		# The signature is intentionally command-only; actor and target scope are
		# resolved from the authenticated session and current Student state.
		self.assertNotIn("actor", inspect.signature(change_student_ownership).parameters)
