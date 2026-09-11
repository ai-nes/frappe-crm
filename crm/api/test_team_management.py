"""Contracts for the Group/Team management workspace API."""

from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.team_management import (
	RECIPIENT_FUNCTIONS,
	_assert_staff_can_be_team_member,
	_assert_staff_not_in_other_team,
	_can_manage_leads,
	_can_manage_team,
	_initials,
	_is_global,
	_member_role,
	_require_access,
	_save_team,
	get_team_management_workspace,
)


class TestTeamManagementWorkspace(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_lead_sale_is_global_but_ceo_and_director_are_not_team_management_profiles(self):
		self.assertTrue(_is_global({"profile": "lead_sales"}))
		self.assertFalse(_is_global({"profile": "ceo"}))
		self.assertFalse(_is_global({"profile": "admissions_director"}))

		for profile, capabilities in (
			("ceo", {"system.configure"}),
			("admissions_director", {"admissions.oversee"}),
		):
			with self.subTest(profile=profile):
				context = {"profile": profile, "capabilities": capabilities}
				with patch("crm.api.team_management._actor_context", return_value=context):
					with self.assertRaises(frappe.PermissionError):
						_require_access()

	def test_system_manager_keeps_technical_global_access(self):
		context = {"profile": "system_manager", "capabilities": {"system.configure"}}
		self.assertTrue(_is_global(context))
		with patch("crm.api.team_management._actor_context", return_value=context):
			self.assertIsNotNone(_require_access(write=True))

	def test_ctv_sale_is_read_only(self):
		context = {"profile": "ctv_sale", "capabilities": {"student.execute"}}
		with patch("crm.api.team_management._actor_context", return_value=context):
			self.assertIsNotNone(_require_access())
			with self.assertRaises(frappe.PermissionError):
				_require_access(write=True)

	def test_group_and_team_scope_permissions_are_separate(self):
		group_lead = {"profile": "sales", "group_lead_groups": ["G-1"]}
		team_lead = {"profile": "sales", "team_lead_teams": ["T-1"]}
		member = {"profile": "sales", "teams": ["T-1"]}
		self.assertTrue(_can_manage_team(group_lead, group_id="G-1"))
		self.assertFalse(_can_manage_team(team_lead, group_id="G-1"))
		self.assertTrue(_can_manage_leads(group_lead, group_id="G-1"))
		self.assertFalse(_can_manage_leads(team_lead, group_id="G-1"))
		self.assertFalse(_can_manage_team(member, group_id="G-1"))

	def test_sale_and_ctv_sale_have_workspace_read_access(self):
		for profile in ("sales", "ctv_sale"):
			with self.subTest(profile=profile):
				context = {"profile": profile, "capabilities": {"student.execute"}}
				with patch("crm.api.team_management._actor_context", return_value=context):
					self.assertEqual(_require_access()["profile"], profile)

	def test_sale_and_lead_sale_can_pass_write_gate_before_scope_validation(self):
		for profile in ("sales", "lead_sales"):
			with self.subTest(profile=profile):
				context = {"profile": profile, "capabilities": {"student.execute"}}
				with patch("crm.api.team_management._actor_context", return_value=context):
					self.assertEqual(_require_access(write=True)["profile"], profile)

	def test_staff_already_in_another_team_is_rejected(self):
		staff = SimpleNamespace(name="S-1")
		with patch(
			"crm.api.team_management._active_memberships",
			return_value=[SimpleNamespace(staff="S-1", team="T-1")],
		):
			with self.assertRaises(frappe.ValidationError) as error:
				_assert_staff_not_in_other_team(staff, "T-2")

		self.assertEqual(error.exception.code, "STAFF_ALREADY_ASSIGNED")

	def test_lead_sale_is_manager_only(self):
		staff = SimpleNamespace(name="S-1", user="lead@example.com")
		with patch("crm.api.team_management.frappe.get_roles", return_value=["Lead Sale"]):
			with self.assertRaises(frappe.ValidationError) as error:
				_assert_staff_can_be_team_member(staff)

		self.assertEqual(error.exception.code, "LEAD_SALE_MANAGER_ONLY")

	def test_new_team_adds_selected_lead_then_keeps_team_lead_pointer(self):
		class FakeTeam:
			name = "T-2"
			team_lead_staff = None

			def insert(self, ignore_permissions=False):
				self.lead_at_insert = self.team_lead_staff

		team = FakeTeam()
		staff = SimpleNamespace(name="S-1", campus="C-1", user=None)
		context = {"profile": "lead_sales"}

		def exists(doctype, *args, **kwargs):
			return doctype == "CRM Campus"

		with (
			patch("crm.api.team_management.frappe.db.exists", side_effect=exists),
			patch("crm.api.team_management.frappe.get_doc", return_value=team),
			patch("crm.api.team_management._staff_doc", return_value=staff),
			patch("crm.api.team_management._assert_staff_can_be_team_member"),
			patch("crm.api.team_management._assert_staff_not_in_other_team"),
			patch("crm.api.team_management._save_membership") as save_membership,
			patch("crm.api.team_management._team_revision", return_value="revision"),
		):
			result = _save_team(
				None,
				"New Team",
				None,
				"Sales",
				None,
				"C-1",
				None,
				"S-1",
				False,
				context,
			)

		self.assertEqual(team.lead_at_insert, "S-1")
		self.assertEqual(result["teamId"], "T-2")
		save_membership.assert_called_once_with(
			"S-1",
			"T-2",
			"Sale",
			False,
			None,
			True,
			context,
		)

	def test_workspace_has_stable_dashboard_contract(self):
		workspace = get_team_management_workspace()

		self.assertEqual(workspace["schemaVersion"], "team-management-v1")
		self.assertIn("summary", workspace)
		self.assertIn("groups", workspace)
		self.assertIn("teams", workspace)
		self.assertIn("members", workspace)
		self.assertIn("options", workspace)
		self.assertIn("availableMembers", workspace)
		self.assertIn("permissions", workspace)
		self.assertIn("provinces", workspace["options"])
		for group in workspace["groups"]:
			self.assertIn("provinceId", group)
			self.assertIn("provinceCode", group)
			self.assertIn("provinceName", group)
		self.assertGreaterEqual(workspace["summary"]["teamCount"], len(workspace["teams"]))
		self.assertTrue(workspace["permissions"]["canManageAll"])
		for member in workspace["availableMembers"]:
			self.assertTrue(member["isActive"])
			self.assertNotEqual(member["role"], "LEAD_SALE")
			self.assertEqual(member["teamIds"], [])

		for team in workspace["teams"]:
			self.assertIn(team["readiness"], {"ready", "not_ready", "inactive"})
			self.assertIn("revision", team)
			self.assertIsInstance(team["memberIds"], list)
			self.assertIn("leadCount", team)
			self.assertIn("saleCount", team)
			self.assertIn("ctvCount", team)
			self.assertIn("poolCount", team)
			self.assertIn("policyCount", team)
			self.assertIn(team["routingReadiness"], {"ready", "not_ready", "inactive"})
			self.assertLessEqual(
				team["leadCount"] + team["saleCount"] + team["ctvCount"], team["memberCount"]
			)
		for group in workspace["groups"]:
			self.assertIn("groupLeadId", group)
			self.assertIn("groupCode", group)
		for team in workspace["teams"]:
			self.assertIn("teamCode", team)
			self.assertIn("groupCode", team)

	def test_member_role_and_initials_are_normalized_for_dashboard(self):
		self.assertEqual(_member_role("Sale"), "SALE")
		self.assertEqual(_member_role("CTV Sale"), "CTV_SALE")
		self.assertEqual(_member_role("Lead Sale"), "LEAD_SALE")
		self.assertEqual(_initials("Nguyễn Minh Khôi"), "NK")
		self.assertEqual(RECIPIENT_FUNCTIONS, {"Sale", "CTV Sale"})

	def test_existing_team_memberships_are_visible_without_ownership_changes(self):
		before = frappe.db.count("CRM Lead")
		workspace = get_team_management_workspace()
		after = frappe.db.count("CRM Lead")

		self.assertEqual(before, after)
		self.assertTrue(any(team["memberCount"] > 0 for team in workspace["teams"]))

	def test_empty_team_is_explicitly_not_ready_for_routing(self):
		workspace = get_team_management_workspace()
		for team in workspace["teams"]:
			if team["memberCount"] == 0 and team["isActive"]:
				self.assertEqual(team["readiness"], "not_ready")
