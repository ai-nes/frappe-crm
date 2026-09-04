import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.agent_migrations import SALES_WORKLIST_ROLE_NAMES
from crm.api.capability import _is_capability_gateway_user
from crm.api.session import (
	_session_role_flags,
	get_crm_user_role,
	me,
	resolve_crm_profile,
)
from crm.api.user import _can_manage_target, _can_remove_target
from crm.fcrm.role_policy import (
	CANONICAL_PERMISSION_MATRIX,
	CRM_ALLOWED_ROLES,
	LEGACY_COMPATIBILITY_OVERLAYS,
	POLICY_VERSION,
	backfill_target_for_roles,
	capabilities_for_roles,
	classify_role_set,
	managed_docperm_rows,
	resolve_compatibility_overlay,
)


class TestSessionRoleContract(FrappeTestCase):
	def test_session_me_exposes_dashboard_permission_list(self):
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		try:
			response = me()
			self.assertEqual(response["permission"], response["crm_capabilities"])
		finally:
			frappe.set_user(previous_user)

	def test_canonical_role_names_resolve_without_legacy_aliases(self):
		self.assertEqual(resolve_crm_profile({"Sale"}), "sales")
		self.assertEqual(resolve_crm_profile({"Lead Sales"}), "lead_sales")
		self.assertEqual(resolve_crm_profile({"Marketing"}), "marketing")
		self.assertEqual(resolve_crm_profile({"Admissions Director"}), "admissions_director")
		self.assertIsNone(resolve_crm_profile({"Giám đốc Tuyển sinh"}))

	def test_legacy_roles_select_one_overlay_instead_of_a_canonical_profile(self):
		for roles, overlay in (
			({"Counseller"}, "counseller_campus"),
			({"Team Leader"}, "team_leader"),
			({"Promoter-PR"}, "promoter_campus"),
			({"Marketing Operator"}, "marketing_operator"),
			({"Admissions Operations"}, "admissions_operations"),
			({"Giám đốc Tuyển sinh"}, "admissions_director_legacy"),
		):
			with self.subTest(roles=roles):
				self.assertIsNone(resolve_crm_profile(roles))
				self.assertEqual(resolve_compatibility_overlay(roles), overlay)
				self.assertEqual(classify_role_set(roles), "compatibility_overlay")
				self.assertEqual(capabilities_for_roles(roles), frozenset())

	def test_retired_sales_role_requires_migration(self):
		self.assertIsNone(resolve_crm_profile({"Sales"}))
		self.assertIsNone(resolve_compatibility_overlay({"Sales"}))
		self.assertEqual(classify_role_set({"Sales"}), "legacy_migration_required")
		self.assertEqual(backfill_target_for_roles({"Sales"}), None)
		self.assertEqual(capabilities_for_roles({"Sales"}), frozenset())
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"Sales"})

	def test_unknown_and_cross_domain_business_profiles_fail_closed(self):
		self.assertIsNone(resolve_crm_profile({"Unrelated Role"}))
		self.assertIsNone(resolve_crm_profile({"Sale", "Unrelated Role"}))
		self.assertEqual(resolve_crm_profile({"Sale", "Team Leader"}), "lead_sales")
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"Unrelated Role"})
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"Sale", "Marketing"})
		self.assertEqual(get_crm_user_role({"Sale", "Team Leader"}), ("Lead Sales", "lead_sales"))

	def test_same_domain_sales_aliases_use_lead_sales_without_capability_union(self):
		for roles in (
			{"Sales Manager", "Sales User"},
			{"Team Leader", "Sale"},
		):
			with self.subTest(roles=roles):
				flags = _session_role_flags(roles)
				self.assertEqual(flags["crm_role_state"], "canonical_profile")
				self.assertEqual(flags["crm_profile"], "lead_sales")
				self.assertEqual(flags["crm_capabilities"], sorted(capabilities_for_roles({"Lead Sales"})))
				self.assertTrue(flags["is_sales_manager"])
				self.assertFalse(flags["is_sales_user"])

	def test_requested_profiles_are_crm_users_without_legacy_elevation(self):
		for roles, profile, label in (
			({"Sale"}, "sales", "Sale"),
			({"Marketing"}, "marketing", "Marketing"),
			({"Lead Sales"}, "lead_sales", "Lead Sales"),
			({"Admissions Director"}, "admissions_director", "Admissions Director"),
		):
			with self.subTest(roles=roles):
				flags = _session_role_flags(roles)
				self.assertTrue(flags["is_crm_user"])
				self.assertEqual(flags["crm_profile"], profile)
				self.assertEqual(flags["is_sales_manager"], profile == "lead_sales")
				self.assertEqual(flags["is_sales_user"], profile == "sales")
				self.assertEqual(get_crm_user_role(roles), (label, profile))

	def test_legacy_overlay_users_keep_crm_entry_without_canonical_capabilities(self):
		flags = _session_role_flags({"Promoter-PR"})
		self.assertTrue(flags["is_crm_user"])
		self.assertIsNone(flags["crm_profile"])
		self.assertEqual(flags["crm_role_state"], "compatibility_overlay")
		self.assertEqual(flags["crm_capabilities"], [])
		self.assertEqual(get_crm_user_role({"Promoter-PR"}), ("Promoter-PR", None))

	def test_system_manager_is_a_crm_user_without_a_business_profile(self):
		flags = _session_role_flags({"System Manager"})
		self.assertTrue(flags["is_system_manager"])
		self.assertTrue(flags["is_crm_user"])
		self.assertIsNone(flags["crm_profile"])

	def test_capabilities_are_server_derived_and_data_steward_is_not_a_profile(self):
		self.assertIn("student.execute", capabilities_for_roles({"Sale"}))
		self.assertIn("system.configure", capabilities_for_roles({"System Manager"}))
		self.assertEqual(capabilities_for_roles({"CRM Data Steward"}), frozenset())
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags({"Marketing", "CRM Data Steward"})
		self.assertEqual(POLICY_VERSION, "phase2-v1")

	def test_canonical_sales_is_eligible_for_the_capability_gateway(self):
		self.assertTrue(_is_capability_gateway_user(_session_role_flags({"Sale"})))
		self.assertTrue(_is_capability_gateway_user(_session_role_flags({"Lead Sales"})))
		self.assertTrue(_is_capability_gateway_user(_session_role_flags({"Marketing"})))
		self.assertFalse(_is_capability_gateway_user(_session_role_flags({"System Manager"})))
		self.assertIn("Sale", CRM_ALLOWED_ROLES)
		self.assertNotIn("Sales", CRM_ALLOWED_ROLES)
		self.assertIn("Sale", SALES_WORKLIST_ROLE_NAMES)
		self.assertNotIn("Sales", SALES_WORKLIST_ROLE_NAMES)
		self.assertIn("Lead Sales", SALES_WORKLIST_ROLE_NAMES)

	def test_permission_matrix_is_complete_and_versioned(self):
		self.assertEqual(
			set(CANONICAL_PERMISSION_MATRIX),
			{
				"attribution_evidence",
				"admissions_case",
				"decision_action",
				"reference",
				"acquisition",
				"governed_acquisition",
				"governed_admissions",
				"control_plane",
				"legacy_untouched",
			},
		)
		self.assertEqual(
			CANONICAL_PERMISSION_MATRIX["admissions_case"]["doctypes"],
			("CRM Student", "CRM Contact"),
		)
		self.assertEqual(CANONICAL_PERMISSION_MATRIX["admissions_case"]["permissions"]["sales"], "rwc")
		self.assertEqual(
			CANONICAL_PERMISSION_MATRIX["governed_admissions"]["per_doctype_permissions"]["CRM Campus"][
				"admissions_director"
			],
			"rwc",
		)
		self.assertEqual(
			CANONICAL_PERMISSION_MATRIX["legacy_untouched"]["permissions"]["marketing"],
			"unchanged",
		)

	def test_legacy_overlay_cannot_become_a_canonical_capability_source(self):
		self.assertEqual(
			LEGACY_COMPATIBILITY_OVERLAYS["marketing_operator"]["roles"],
			frozenset({"Marketing Operator"}),
		)
		self.assertNotIn(
			"CRM Data Steward",
			{role for overlay in LEGACY_COMPATIBILITY_OVERLAYS.values() for role in overlay["roles"]},
		)
		self.assertEqual(resolve_compatibility_overlay({"Counseller"}), "counseller_campus")
		self.assertEqual(resolve_compatibility_overlay({"Sales Manager"}), "team_leader")
		self.assertIsNone(resolve_compatibility_overlay({"Counseller", "Sale"}))
		self.assertIsNone(resolve_compatibility_overlay({"Sales Manager", "System Manager"}))
		self.assertEqual(classify_role_set({"Marketing Operator"}), "compatibility_overlay")
		self.assertEqual(classify_role_set({"Admissions Operations"}), "compatibility_overlay")
		self.assertEqual(classify_role_set({"Unknown Legacy Role"}), "unmapped")
		self.assertEqual(classify_role_set({"CRM Data Steward"}), "legacy_migration_required")
		self.assertEqual(classify_role_set({"Sales"}), "legacy_migration_required")

	def test_legacy_sales_manager_cannot_modify_other_business_profiles(self):
		self.assertTrue(_can_manage_target(False, set()))
		self.assertFalse(_can_manage_target(False, {"Sales Manager", "Sale"}))
		self.assertFalse(_can_manage_target(False, {"Marketing"}))
		self.assertFalse(_can_manage_target(False, {"Lead Sales"}))
		self.assertTrue(_can_manage_target(True, {"Marketing"}))
		self.assertFalse(_can_remove_target(False, {"System Manager"}))
		self.assertTrue(_can_remove_target(True, {"System Manager"}))

	def test_managed_docperm_rows_are_policy_derived_and_preserve_legacy_untouched(self):
		student_roles = {row["role"]: row for row in managed_docperm_rows()["CRM Student"]}
		self.assertEqual(
			{key for key, value in student_roles["Sale"].items() if value == 1},
			{"read", "write", "create"},
		)
		self.assertNotIn("Team Leader", student_roles)
		self.assertNotIn("Sales", student_roles)
		self.assertNotIn("CRM Staff", managed_docperm_rows())
		self.assertNotIn("CRM Data Steward", student_roles)

	def test_system_manager_precedes_business_roles_as_control_plane_only(self):
		roles = {"System Manager", "Sale", "Team Leader", "Marketing"}
		self.assertEqual(classify_role_set(roles), "system_manager")
		self.assertEqual(capabilities_for_roles(roles), capabilities_for_roles({"System Manager"}))
		flags = _session_role_flags(roles)
		self.assertTrue(flags["is_system_manager"])
		self.assertFalse(flags["is_sales_manager"])
		self.assertFalse(flags["is_sales_user"])
		self.assertIsNone(flags["crm_profile"])
		self.assertEqual(get_crm_user_role(roles), ("System Manager", None))

	def test_system_manager_retains_crm_access_with_desk_management_roles(self):
		roles = {"System Manager", "Workspace Manager", "Dashboard Manager", "Report Manager"}
		self.assertEqual(classify_role_set(roles), "system_manager")
		self.assertEqual(capabilities_for_roles(roles), capabilities_for_roles({"System Manager"}))
		flags = _session_role_flags(roles)
		self.assertTrue(flags["is_system_manager"])
		self.assertIsNone(flags["crm_profile"])
		self.assertEqual(get_crm_user_role(roles), ("System Manager", None))

	def test_system_manager_with_unknown_role_fails_closed(self):
		roles = {"System Manager", "Unrecognized Role"}
		self.assertEqual(classify_role_set(roles), "mixed_or_unmapped")
		self.assertEqual(capabilities_for_roles(roles), frozenset())
		with self.assertRaises(frappe.PermissionError):
			_session_role_flags(roles)

	def test_legacy_role_sources_have_one_explicit_backfill_target(self):
		self.assertEqual(backfill_target_for_roles({"Sales User"}), "Sale")
		self.assertEqual(backfill_target_for_roles({"Sales Manager"}), "Lead Sales")
		self.assertEqual(backfill_target_for_roles({"Marketing Operator"}), "Marketing")
		self.assertEqual(backfill_target_for_roles({"Admissions Operations"}), "Admissions Director")
		self.assertIsNone(backfill_target_for_roles({"Sales User", "Sales Manager"}))
