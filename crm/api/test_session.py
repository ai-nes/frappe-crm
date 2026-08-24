import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.session import (
	_session_role_flags,
	get_crm_user_role,
	resolve_copilot_profile,
	resolve_crm_profile,
)


class TestSessionRoleContract(FrappeTestCase):
	def test_only_canonical_roles_resolve(self):
		for role in ("Sale", "Marketing", "Lead Sales", "Admissions Director"):
			with self.subTest(role=role):
				self.assertEqual(resolve_crm_profile({role}), role)
		self.assertIsNone(resolve_crm_profile({"Sales Manager"}))
		self.assertIsNone(resolve_crm_profile({"Team Leader"}))

	def test_unknown_and_mixed_business_profiles_fail_closed(self):
		self.assertIsNone(resolve_crm_profile({"Unrelated Role"}))
		self.assertIsNone(resolve_crm_profile({"Sale", "Lead Sales"}))
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"Unrelated Role"})
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"Sale", "Lead Sales"})
		flags = _session_role_flags({"System Manager", "Sale", "Lead Sales"})
		self.assertTrue(flags["is_system_manager"])
		self.assertIsNone(flags["crm_role"])
		self.assertEqual(get_crm_user_role({"System Manager", "Sale", "Lead Sales"}), ("System Manager", None))

	def test_requested_roles_are_crm_users(self):
		for roles, role in (
			({"Sale"}, "Sale"),
			({"Marketing"}, "Marketing"),
			({"Lead Sales"}, "Lead Sales"),
			({"Admissions Director"}, "Admissions Director"),
		):
			with self.subTest(roles=roles):
				flags = _session_role_flags(roles)
				self.assertTrue(flags["is_crm_user"])
				self.assertEqual(flags["crm_role"], role)
				self.assertEqual(get_crm_user_role(roles), (role, role))

	def test_system_manager_is_a_crm_user_without_a_business_profile(self):
		flags = _session_role_flags({"System Manager"})
		self.assertTrue(flags["is_system_manager"])
		self.assertTrue(flags["is_crm_user"])
		self.assertIsNone(flags["crm_role"])

	def test_system_manager_is_always_denied_a_copilot_profile(self):
		self.assertIsNone(resolve_copilot_profile({"System Manager"}))
		self.assertIsNone(resolve_copilot_profile({"System Manager", "Sale"}))
