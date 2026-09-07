"""Focused contract tests for the Phase 3 ownership command adapter."""

import inspect
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import student_lead_operations as student_lead_operations_api
from crm.api import student_ownership as student_ownership_api
from crm.api.student_ownership import change_student_ownership
from crm.fcrm import student_ownership as student_ownership_domain
from crm.fcrm.role_policy import capabilities_for_roles
from crm.fcrm.student_ownership import (
	StudentOwnershipError,
	_length_delimited,
	ownership_command_keys,
)


class TestStudentOwnershipContract(FrappeTestCase):
	def test_only_sale_and_managers_receive_ownership_capability(self):
		for roles in ({"Sale"}, {"Lead Sale"}, {"Admissions Director"}):
			with self.subTest(roles=roles):
				self.assertIn("student.ownership.manage", capabilities_for_roles(roles))
		for roles in ({"CTV Sale"}, {"Marketing"}, {"System Manager"}, {"Team Leader"}, {"Sales Manager"}):
			self.assertNotIn("student.ownership.manage", capabilities_for_roles(roles))

	def test_only_sale_can_authorize_public_ownership_command(self):
		with patch.object(frappe, "get_roles", return_value=["Sale"]):
			resolved_profile, policy = student_ownership_domain._authorize("sale@example.com")

		self.assertEqual(resolved_profile, "sales")
		self.assertEqual(policy["profile"], "sales")

		with patch.object(frappe, "get_roles", return_value=["CTV Sale"]):
			with self.assertRaises(StudentOwnershipError) as error:
				student_ownership_domain._authorize("ctv@example.com")

		self.assertEqual(error.exception.code, "UNAUTHORIZED")

	def test_sales_cannot_assign_students_to_a_pool(self):
		with patch.object(student_ownership_domain, "_authorize", return_value=("sales", {})):
			with self.assertRaises(StudentOwnershipError) as error:
				student_ownership_domain.resolve_student_operational_target(
					frappe._dict(branch="CAMPUS-1"), "pool", "POOL-1", actor="sale@example.com"
				)

		self.assertEqual(error.exception.code, "UNAUTHORIZED")

	def test_sale_can_read_team_pool_student_for_assignment_flow(self):
		student = frappe._dict(name="STUDENT-POOL-1", branch="CAMPUS-1")
		with (
			patch.object(
				student_ownership_domain,
				"_read_actor",
				return_value=("sale@example.com", "sales", set()),
			),
			patch.object(student_ownership_domain.frappe, "get_doc", return_value=student),
			patch.object(
				student_ownership_domain,
				"has_student_list_read_permission",
				return_value=True,
			) as read_permission,
		):
			result = student_ownership_domain._student_for_read(student.name)

		self.assertIs(result[0], student)
		read_permission.assert_called_once_with(student, user="sale@example.com")

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
	def test_lead_sale_fairness_report_is_scoped_to_its_team_staff(self):
		frappe.set_user("lead-sale@example.com")
		try:
			with (
				patch.object(frappe, "get_roles", return_value=["Lead Sale"]),
				patch.object(
					student_lead_operations_api,
					"_team_staff_scope",
					return_value={"STAFF-SALE"},
				),
				patch.object(
					student_lead_operations_api,
					"fairness_summary",
					return_value={"counts": {}},
				) as fairness_summary,
			):
				student_lead_operations_api.fairness_report_read(zone="ZONE-1")
			fairness_summary.assert_called_once_with(
				zone="ZONE-1", since=None, until=None, staff_scope={"STAFF-SALE"}
			)
		finally:
			frappe.set_user("Administrator")

	def test_student_management_reports_reject_sale_and_ctv(self):
		for role in ("Sale", "CTV Sale"):
			with self.subTest(role=role), patch.object(frappe, "get_roles", return_value=[role]):
				frappe.set_user(f"{role.lower().replace(' ', '-')}@example.com")
				try:
					with self.assertRaises(frappe.PermissionError):
						student_lead_operations_api.fairness_report_read()
					with self.assertRaises(frappe.PermissionError):
						student_lead_operations_api.open_ctv_batch_command("STAFF-1", "TEAM-1")
				finally:
					frappe.set_user("Administrator")

	def test_ctv_batch_command_requires_the_authenticated_ctv_owner(self):
		frappe.set_user("ctv@example.com")
		try:
			with (
				patch.object(frappe, "get_roles", return_value=["CTV Sale"]),
				patch.object(
					frappe.db,
					"get_value",
					return_value=frappe._dict(name="STAFF-CTV", is_active=1),
				),
				patch.object(frappe, "get_all", return_value=[]),
			):
				with self.assertRaises(frappe.PermissionError):
					student_lead_operations_api.open_ctv_batch_command("STAFF-OTHER", "TEAM-1")
		finally:
			frappe.set_user("Administrator")

	def test_manager_reassign_remains_restricted_to_manager_profiles(self):
		frappe.set_user("sale@example.com")
		try:
			with patch.object(frappe, "get_roles", return_value=["Sale"]):
				with self.assertRaises(frappe.PermissionError):
					student_lead_operations_api.manager_reassign(
						"STUDENT-1", "STAFF-2", "TEAM-1", "Transfer", 1
					)
		finally:
			frappe.set_user("Administrator")

	def test_api_does_not_accept_actor_or_scope_parameters(self):
		# The signature is intentionally command-only; actor and target scope are
		# resolved from the authenticated session and current Student state.
		self.assertNotIn("actor", inspect.signature(change_student_ownership).parameters)

	def test_assignable_sales_exposes_sale_and_ctv_sale_candidates(self):
		with patch.object(
			student_ownership_api,
			"_get_eligible_ownership_targets",
			return_value={
				"owners": [
					{"name": "STAFF-SALE", "profile": "sales"},
					{"name": "STAFF-CTV", "profile": "ctv_sale"},
				],
				"pools": [],
			},
		):
			response = student_ownership_api.get_assignable_sales(studentId="STUDENT-1")

		self.assertEqual(response["studentId"], "STUDENT-1")
		self.assertEqual([row["name"] for row in response["sales"]], ["STAFF-SALE", "STAFF-CTV"])

	def test_assignable_sales_get_excludes_lead_sale_candidates(self):
		with patch.object(
			student_ownership_api,
			"_get_eligible_ownership_targets",
			return_value={
				"owners": [
					{"name": "STAFF-SALE", "profile": "sales"},
					{"name": "STAFF-CTV", "profile": "ctv_sale"},
					{"name": "STAFF-LEAD", "profile": "lead_sales", "role": "Lead Sale"},
				],
				"pools": [],
			},
		):
			response = student_ownership_api.get_assignable_sales(studentId="STUDENT-1")

		self.assertEqual([row["name"] for row in response["sales"]], ["STAFF-SALE", "STAFF-CTV"])

	def test_assignable_sales_search_is_case_and_accent_insensitive(self):
		with patch.object(
			student_ownership_api,
			"_get_eligible_ownership_targets",
			return_value={
				"owners": [
					{
						"name": "STAFF-1",
						"label": "Nguyễn Minh Ánh",
						"profile": "sales",
						"role": "Sale",
						"team": "TEAM-1",
					},
					{
						"name": "STAFF-2",
						"label": "CTV Bình Minh",
						"profile": "ctv_sale",
						"role": "CTV Sale",
						"function": "CTV Sale",
					},
				],
				"pools": [],
			},
		):
			self.assertEqual(
				[
					row["name"]
					for row in student_ownership_api.get_assignable_sales("STUDENT-1", "nguyen")["sales"]
				],
				["STAFF-1"],
			)
			self.assertEqual(
				[
					row["name"]
					for row in student_ownership_api.get_assignable_sales("STUDENT-1", search="CTV")["sales"]
				],
				["STAFF-2"],
			)
			self.assertEqual(
				student_ownership_api.get_assignable_sales("STUDENT-1", search="unknown")["sales"], []
			)

	def test_assign_student_to_sales_resolves_team_and_uses_canonical_command(self):
		with (
			patch.object(
				student_ownership_api,
				"_get_eligible_ownership_targets",
				return_value={
					"owners": [{"name": "STAFF-CTV", "profile": "ctv_sale", "team": "TEAM-1"}],
					"pools": [],
				},
			),
			patch.object(
				student_ownership_api,
				"_get_student_ownership",
				return_value={"revision": 4},
			),
			patch.object(
				student_ownership_api,
				"_change_student_ownership",
				return_value={"status": "applied", "owner_staff": "STAFF-CTV"},
			) as change,
		):
			response = student_ownership_api.assign_student_to_sales(
				studentId="STUDENT-1",
				ownerId="STAFF-CTV",
				reason="Manager assigned the student to the CTV Sale.",
			)

		self.assertEqual(response["owner_staff"], "STAFF-CTV")
		call = change.call_args.kwargs
		self.assertEqual(
			{
				key: call[key]
				for key in (
					"student",
					"target_kind",
					"target_id",
					"target_team_id",
					"reason",
					"expected_revision",
				)
			},
			{
				"student": "STUDENT-1",
				"target_kind": "owner",
				"target_id": "STAFF-CTV",
				"target_team_id": "TEAM-1",
				"reason": "Manager assigned the student to the CTV Sale.",
				"expected_revision": 4,
			},
		)
		self.assertTrue(call["idempotency_key"].startswith("manual-student-assignment:"))
		self.assertTrue(call["correlation_id"].startswith("manual-student-assignment:"))

	def test_domain_eligible_targets_include_ctv_sale_staff(self):
		teams = [frappe._dict(name="TEAM-1", team_name="Team 1", campus="CAMPUS-1", is_active=1)]
		staff_rows = [
			frappe._dict(name="STAFF-SALE", full_name="Sale", user="sale@example.com", campus="CAMPUS-1"),
			frappe._dict(name="STAFF-CTV", full_name="CTV Sale", user="ctv@example.com", campus="CAMPUS-1"),
		]
		with (
			patch.object(
				student_ownership_domain,
				"_student_for_read",
				return_value=(
					frappe._dict(name="STUDENT-1", branch="CAMPUS-1"),
					"manager@example.com",
					"admissions_director",
					set(),
				),
			),
			patch.object(student_ownership_domain, "_authorize"),
			patch.object(
				student_ownership_domain,
				"resolve_crm_profile",
				side_effect=lambda roles: "ctv_sale" if "CTV Sale" in roles else "sales",
			),
			patch.object(
				frappe,
				"get_roles",
				side_effect=lambda user: {"sale@example.com": {"Sale"}, "ctv@example.com": {"CTV Sale"}}[
					user
				],
			),
			patch.object(frappe.db, "get_value", return_value=1),
			patch.object(
				frappe,
				"get_all",
				side_effect=[
					teams,
					[],
					staff_rows,
					[frappe._dict(name="MEM-SALE", team="TEAM-1", function="Sale")],
					[frappe._dict(name="MEM-CTV", team="TEAM-1", function="CTV Sale")],
				],
			),
		):
			response = student_ownership_domain.get_eligible_ownership_targets("STUDENT-1")

		self.assertEqual([row["profile"] for row in response["owners"]], ["sales", "ctv_sale"])
		self.assertEqual([row["role"] for row in response["owners"]], ["Sale", "CTV Sale"])

	def test_sales_target_listing_is_limited_to_actor_team(self):
		teams = [
			frappe._dict(name="TEAM-1", team_name="Team 1", campus="CAMPUS-1", is_active=1),
			frappe._dict(name="TEAM-2", team_name="Team 2", campus="CAMPUS-1", is_active=1),
		]
		staff_rows = [
			frappe._dict(name="STAFF-1", full_name="Sale 1", user="sale-1@example.com", campus="CAMPUS-1"),
			frappe._dict(name="STAFF-2", full_name="Sale 2", user="sale-2@example.com", campus="CAMPUS-1"),
		]
		memberships = {
			"STAFF-1": [frappe._dict(name="MEM-1", team="TEAM-1", function="Sale")],
			"STAFF-2": [frappe._dict(name="MEM-2", team="TEAM-2", function="Sale")],
		}

		def get_all(doctype, filters=None, **_kwargs):
			if doctype == "CRM Team":
				return teams
			if doctype == "CRM Student Pool":
				return []
			if doctype == "CRM Staff":
				return staff_rows
			if doctype == "CRM Team Membership":
				return memberships[filters["parent"]]
			return []

		with (
			patch.object(
				student_ownership_domain,
				"_student_for_read",
				return_value=(frappe._dict(name="STUDENT-1", branch="CAMPUS-1"), "sale@example.com", "sales", set()),
			),
			patch.object(student_ownership_domain, "_authorize"),
			patch.object(student_ownership_domain, "_team_rows_for_actor", return_value=[teams[0]]),
			patch.object(student_ownership_domain.frappe, "get_all", side_effect=get_all),
			patch.object(
				student_ownership_domain.frappe,
				"get_roles",
				side_effect=lambda user: {"sale-1@example.com": {"Sale"}, "sale-2@example.com": {"Sale"}}[user],
			),
			patch.object(student_ownership_domain.frappe.db, "get_value", return_value=1),
		):
			response = student_ownership_domain.get_eligible_ownership_targets("STUDENT-1")

		self.assertEqual([row["name"] for row in response["owners"]], ["STAFF-1"])
