from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from crm.demo import repair_operational_accounts


class FakeUser:
	def __init__(self):
		self.name = "lead@example.com"
		self.enabled = 1
		self.roles = [SimpleNamespace(role="Lead Sales"), SimpleNamespace(role="Employee")]
		self.saved = False

	def get(self, key):
		return getattr(self, key, None)

	def save(self, **kwargs):
		self.saved = True


class TestRepairOperationalAccounts(TestCase):
	def test_audit_marks_legacy_role_and_suggests_canonical_target(self):
		result = repair_operational_accounts._audit_account(
			{"name": "lead@example.com", "email": "lead@example.com", "enabled": 1},
			{"Lead Sales"},
			[],
			[],
			{},
			today_value="2026-09-08",
		)

		self.assertEqual(result["role_state"], "unmapped")
		self.assertIsNone(result["crm_profile"])
		self.assertEqual(result["recommended_role"], "Lead Sale")
		self.assertEqual(
			{issue["code"] for issue in result["issues"]},
			{"ROLE_NOT_CANONICAL"},
		)

	def test_audit_marks_healthy_sale_identity_and_team_scope(self):
		result = repair_operational_accounts._audit_account(
			{"name": "sale@example.com", "email": "sale@example.com", "enabled": 1},
			{"Sale"},
			[
				{
					"name": "STAFF-1",
					"full_name": "Sale User",
					"user": "sale@example.com",
					"is_active": 1,
					"department": "Admissions HCM",
					"campus": "HCM",
					"department_exists": True,
					"campus_exists": True,
					"department_campus": "HCM",
				}
			],
			[
				{
					"staff": "STAFF-1",
					"team": "TEAM-HCM",
					"function": "Sale",
					"is_primary": 1,
					"effective_from": "2026-01-01",
					"effective_until": None,
				}
			],
			{
				"TEAM-HCM": {
					"name": "TEAM-HCM",
					"campus": "HCM",
					"team_type": "Sales",
					"is_active": 1,
				}
			},
			today_value="2026-09-08",
		)

		self.assertEqual(result["crm_profile"], "sales")
		self.assertEqual(result["recommended_role"], "Sale")
		self.assertEqual(result["issues"], [])

	def test_audit_does_not_require_staff_for_admissions_director(self):
		result = repair_operational_accounts._audit_account(
			{"name": "director@example.com", "email": "director@example.com", "enabled": 1},
			{"Admissions Director"},
			[],
			[],
			{},
			today_value="2026-09-08",
		)

		self.assertEqual(result["crm_profile"], "admissions_director")
		self.assertEqual(result["issues"], [])

	def test_normalize_accounts_requires_canonical_operational_role(self):
		accounts = repair_operational_accounts._normalize_accounts(
			[
				{
					"email": "sale@example.com",
					"role": "Sale",
					"department": "Admissions",
					"campus": "HCM",
					"team": "Sales HCM",
				}
			]
		)

		self.assertEqual(accounts[0]["email"], "sale@example.com")
		self.assertEqual(accounts[0]["role"], "Sale")
		self.assertEqual(accounts[0]["function"], "Sale")

		with self.assertRaises(Exception):
			repair_operational_accounts._normalize_accounts(
				[{"email": "lead@example.com", "role": "Lead Sales"}]
			)

	def test_prepare_user_profile_removes_legacy_role_without_touching_password(self):
		user = FakeUser()

		with patch.object(repair_operational_accounts, "set_canonical_crm_profile") as set_profile:
			repair_operational_accounts._prepare_user_profile(user, "Lead Sale")

		set_profile.assert_called_once_with(user, "Lead Sale")
		self.assertEqual([row.role for row in user.roles], ["Employee"])
		self.assertTrue(user.saved)

	def test_execute_repairs_all_accounts_atomically(self):
		with (
			patch.object(repair_operational_accounts, "_require_admin_context"),
			patch.object(
				repair_operational_accounts,
				"_repair_account",
				side_effect=[
					{"email": "sale@example.com", "staff": "Sale Staff"},
					{"email": "lead@example.com", "staff": "Lead Staff"},
				],
			) as repair,
			patch.object(repair_operational_accounts.frappe.db, "commit") as commit,
		):
			result = repair_operational_accounts.execute(
				accounts=[
					{"email": "sale@example.com", "role": "Sale"},
					{"email": "lead@example.com", "role": "Lead Sale"},
				]
			)

		self.assertEqual(result["status"], "repaired")
		self.assertEqual(result["count"], 2)
		self.assertEqual(repair.call_count, 2)
		commit.assert_called_once_with()

	def test_execute_rolls_back_when_one_account_cannot_be_repaired(self):
		with (
			patch.object(repair_operational_accounts, "_require_admin_context"),
			patch.object(
				repair_operational_accounts,
				"_repair_account",
				side_effect=repair_operational_accounts.frappe.ValidationError("invalid account"),
			),
			patch.object(repair_operational_accounts.frappe.db, "commit") as commit,
			patch.object(repair_operational_accounts.frappe.db, "rollback") as rollback,
		):
			with self.assertRaises(repair_operational_accounts.frappe.ValidationError):
				repair_operational_accounts.execute(accounts=[{"email": "sale@example.com", "role": "Sale"}])

		commit.assert_not_called()
		rollback.assert_called_once_with()


if __name__ == "__main__":
	import unittest

	unittest.main()
