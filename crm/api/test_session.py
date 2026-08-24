import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.session import _session_role_flags, get_crm_user_role, resolve_crm_profile
from crm.api.user import _can_manage_target, _can_remove_target


class TestSessionRoleContract(FrappeTestCase):
	def test_aliases_resolve_to_the_same_canonical_profile(self):
		self.assertEqual(resolve_crm_profile({"Sale", "CTV-Sale", "Counseller"}), "sales")
		self.assertEqual(resolve_crm_profile({"Marketing", "Promoter-PR"}), "marketing")
		self.assertEqual(resolve_crm_profile({"Team Leader", "Lead Sales"}), "lead_sales")
		self.assertEqual(resolve_crm_profile({"Giám đốc Tuyển sinh"}), "admissions_director")

	def test_legacy_sales_roles_remain_sales_aliases(self):
		self.assertEqual(resolve_crm_profile({"Sales Manager"}), "sales")
		self.assertEqual(resolve_crm_profile({"Sales User"}), "sales")

	def test_unknown_and_mixed_business_profiles_fail_closed(self):
		self.assertIsNone(resolve_crm_profile({"Unrelated Role"}))
		self.assertIsNone(resolve_crm_profile({"Sale", "Team Leader"}))
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"Unrelated Role"})
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"Sale", "Team Leader"})
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"System Manager", "Sale", "Team Leader"})
		self.assertEqual(get_crm_user_role({"System Manager", "Sale", "Team Leader"}), ("", None))

	def test_requested_profiles_are_crm_users_without_legacy_elevation(self):
		for roles, profile, label in (
			({"Sale"}, "sales", "Sales"),
			({"Counseller"}, "sales", "Sales"),
			({"Marketing"}, "marketing", "Marketing"),
			({"Team Leader"}, "lead_sales", "Lead Sales"),
		):
			with self.subTest(roles=roles):
				flags = _session_role_flags(roles)
				self.assertTrue(flags["is_crm_user"])
				self.assertEqual(flags["crm_profile"], profile)
				self.assertFalse(flags["is_sales_manager"])
				self.assertFalse(flags["is_sales_user"])
				self.assertEqual(get_crm_user_role(roles), (label, profile))

	def test_system_manager_is_a_crm_user_without_a_business_profile(self):
		flags = _session_role_flags({"System Manager"})
		self.assertTrue(flags["is_system_manager"])
		self.assertTrue(flags["is_crm_user"])
		self.assertIsNone(flags["crm_profile"])

	def test_legacy_sales_manager_cannot_modify_other_business_profiles(self):
		self.assertTrue(_can_manage_target(False, set()))
		self.assertTrue(_can_manage_target(False, {"Sales Manager", "Sale"}))
		self.assertFalse(_can_manage_target(False, {"Marketing"}))
		self.assertFalse(_can_manage_target(False, {"Lead Sales"}))
		self.assertTrue(_can_manage_target(True, {"Marketing"}))
		self.assertFalse(_can_remove_target(False, {"System Manager"}))
		self.assertTrue(_can_remove_target(True, {"System Manager"}))
