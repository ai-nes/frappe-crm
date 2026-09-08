"""Contracts for the Group/Team management workspace API."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.team_management import (
	RECIPIENT_FUNCTIONS,
	_initials,
	_is_global,
	_member_role,
	_require_access,
	get_team_management_workspace,
)


class TestTeamManagementWorkspace(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_ceo_and_director_have_global_read_write_access(self):
		for profile, capabilities in (
			("ceo", {"system.configure"}),
			("admissions_director", {"admissions.oversee"}),
		):
			with self.subTest(profile=profile):
				context = {"profile": profile, "capabilities": capabilities}
				self.assertTrue(_is_global(context))
				with patch("crm.api.team_management._actor_context", return_value=context):
					self.assertIs(_require_access(write=True), context)

	def test_sale_and_ctv_sale_have_workspace_read_access(self):
		for profile in ("sales", "ctv_sale"):
			with self.subTest(profile=profile):
				context = {"profile": profile, "capabilities": {"student.execute"}}
				with patch("crm.api.team_management._actor_context", return_value=context):
					self.assertIs(_require_access(), context)

	def test_sale_and_lead_sale_have_temporary_team_management_write_access(self):
		for profile in ("sales", "lead_sales"):
			with self.subTest(profile=profile):
				context = {"profile": profile, "capabilities": {"student.execute"}}
				with patch("crm.api.team_management._actor_context", return_value=context):
					self.assertIs(_require_access(write=True), context)

	def test_workspace_has_stable_dashboard_contract(self):
		workspace = get_team_management_workspace()

		self.assertEqual(workspace["schemaVersion"], "team-management-v1")
		self.assertIn("summary", workspace)
		self.assertIn("groups", workspace)
		self.assertIn("teams", workspace)
		self.assertIn("members", workspace)
		self.assertIn("options", workspace)
		self.assertIn("permissions", workspace)
		self.assertIn("provinces", workspace["options"])
		for group in workspace["groups"]:
			self.assertIn("provinceId", group)
			self.assertIn("provinceCode", group)
			self.assertIn("provinceName", group)
		self.assertGreaterEqual(workspace["summary"]["teamCount"], len(workspace["teams"]))
		self.assertTrue(workspace["permissions"]["canManageAll"])

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
