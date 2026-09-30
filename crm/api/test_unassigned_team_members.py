"""Regression coverage for account provisioning and unassigned team candidates."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.team_management import (
	_assert_staff_can_be_team_member,
	_read_workspace,
	_save_membership,
	get_team_management_workspace,
)
from crm.api.user import create_crm_user, update_user_role
from crm.fcrm.staff_provisioning import ensure_sales_staff


class TestUnassignedTeamMembers(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint("unassigned_members_test")
		self.suffix = frappe.generate_hash(length=10)
		department = frappe.get_all("CRM Department", fields=["name", "campus"], limit=1)[0]
		self.campus = department.campus
		self.department = department.name

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point="unassigned_members_test")

	def make_user(self, role="Sale", label="candidate"):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": f"{label}-{self.suffix}@example.com",
				"first_name": f"Candidate {label} {self.suffix}",
				"enabled": 1,
				"send_welcome_email": 0,
				"roles": [{"role": role}],
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "User Permission",
				"user": user.name,
				"allow": "CRM Department",
				"for_value": self.department,
			}
		).insert(ignore_permissions=True)
		return user

	def test_sale_and_ctv_without_team_are_available_with_correct_role(self):
		for role, expected in (("Sale", "SALE"), ("CTV Sale", "CTV_SALE")):
			user = self.make_user(role, expected.lower())
			staff = ensure_sales_staff(user)
			self.assertEqual(ensure_sales_staff(user), staff)
			self.assertEqual(frappe.db.count("CRM Staff", {"user": user.name}), 1)
			workspace = get_team_management_workspace()
			member = next(r for r in workspace["availableMembers"] if r["id"] == staff)
			self.assertEqual(member["role"], expected)
			self.assertEqual(member["teamIds"], [])

	def test_adding_candidate_removes_them_from_available_members(self):
		user = self.make_user("CTV Sale")
		staff = ensure_sales_staff(user)
		team = frappe.get_doc(
			{
				"doctype": "CRM Team",
				"team_name": f"Candidate Team {self.suffix}",
				"campus": self.campus,
				"team_type": "Sales",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		_save_membership(staff, team.name, "CTV Sale", False, None, False, {"profile": "system_manager"})
		workspace = get_team_management_workspace()
		self.assertNotIn(staff, [r["id"] for r in workspace["availableMembers"]])
		member = next(r for r in workspace["members"] if r["id"] == staff)
		self.assertEqual(member["teamIds"], [team.name])
		scoped = _read_workspace({"profile": "sales", "staff": staff, "campuses": [self.campus], "teams": []})
		self.assertNotIn(staff, [r["id"] for r in scoped["availableMembers"]])
		with self.assertRaises(frappe.ValidationError):
			from crm.api.team_management import _assert_staff_not_in_other_team

			_assert_staff_not_in_other_team(frappe.get_doc("CRM Staff", staff), "other-team")

	def test_disabled_and_non_sales_accounts_are_not_candidates(self):
		user = self.make_user()
		staff = ensure_sales_staff(user)
		user.enabled = 0
		user.save(ignore_permissions=True)
		self.assertNotIn(staff, [r["id"] for r in get_team_management_workspace()["availableMembers"]])
		with self.assertRaises(frappe.ValidationError):
			_assert_staff_can_be_team_member(frappe.get_doc("CRM Staff", staff))
		user.enabled = 1
		user.set("roles", [{"role": "Marketing"}])
		user.save(ignore_permissions=True)
		self.assertNotIn(staff, [r["id"] for r in get_team_management_workspace()["availableMembers"]])
		with self.assertRaises(frappe.ValidationError):
			_assert_staff_can_be_team_member(frappe.get_doc("CRM Staff", staff))

	def test_ambiguous_organization_is_not_guessed(self):
		user = self.make_user()
		frappe.db.delete("User Permission", {"user": user.name})
		frappe.get_doc(
			{"doctype": "CRM Department", "department_name": f"Other {self.suffix}", "campus": self.campus}
		).insert(ignore_permissions=True)
		self.assertIsNone(ensure_sales_staff(user))
		self.assertFalse(frappe.db.exists("CRM Staff", {"user": user.name}))

	def test_existing_inactive_staff_is_not_reactivated(self):
		user = self.make_user()
		staff = ensure_sales_staff(user)
		frappe.db.set_value("CRM Staff", staff, "is_active", 0)
		self.assertEqual(ensure_sales_staff(user), staff)
		self.assertEqual(frappe.db.get_value("CRM Staff", staff, "is_active"), 0)

	def test_role_change_provisions_missing_staff(self):
		user = self.make_user("Marketing")
		self.assertIsNone(ensure_sales_staff(user))
		update_user_role(user.name, "CTV Sale")
		staff = frappe.db.get_value("CRM Staff", {"user": user.name}, "name")
		self.assertTrue(staff)
		member = next(r for r in get_team_management_workspace()["availableMembers"] if r["id"] == staff)
		self.assertEqual(member["role"], "CTV_SALE")

	def test_out_of_scope_campus_candidates_are_hidden(self):
		staff = ensure_sales_staff(self.make_user())
		workspace = _read_workspace({"profile": "sales", "campuses": ["other-campus"], "teams": []})
		self.assertNotIn(staff, [r["id"] for r in workspace["members"]])

	def test_create_user_calls_staff_provisioning(self):
		with (
			patch("crm.api.user._assert_password_strength"),
			patch("crm.api.user.update_password"),
			patch("crm.api.user.ensure_sales_staff") as provision,
		):
			name = create_crm_user(
				f"created-{self.suffix}@example.com", "Created Candidate", "unused", "CTV Sale"
			)
		provision.assert_called_once()
		self.assertEqual(provision.call_args.args[0].name, name)
