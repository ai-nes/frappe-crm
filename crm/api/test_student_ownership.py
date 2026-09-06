"""Focused contract tests for the Phase 3 ownership command adapter."""

import inspect
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

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
	def test_only_lead_sales_and_admissions_director_receive_capability(self):
		self.assertIn("student.ownership.manage", capabilities_for_roles({"Lead Sale"}))
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

	def test_assignable_sales_search_is_case_and_accent_insensitive(self):
		with patch.object(
			student_ownership_api,
			"_get_eligible_ownership_targets",
			return_value={
				"owners": [
					{
						"name": "STAFF-1",
						"label": "Nguyễn Minh Ánh",
						"role": "Sale",
						"team": "TEAM-1",
					},
					{
						"name": "STAFF-2",
						"label": "CTV Bình Minh",
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
				return_value={"owners": [{"name": "STAFF-CTV", "team": "TEAM-1"}], "pools": []},
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
