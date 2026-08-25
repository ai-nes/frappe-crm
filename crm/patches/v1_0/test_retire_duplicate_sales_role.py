from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.patches.v1_0 import retire_duplicate_sales_role


class TestRetireDuplicateSalesRole(FrappeTestCase):
	def test_target_is_sale_only_for_unambiguous_sales_sources(self):
		self.assertEqual(retire_duplicate_sales_role._target_for_roles({"Sales"}), "Sale")
		self.assertEqual(
			retire_duplicate_sales_role._target_for_roles({"Sales", "Sales User"}),
			"Sale",
		)
		self.assertIsNone(
			retire_duplicate_sales_role._target_for_roles({"Sales", "Sales Manager"}),
		)
		self.assertIsNone(
			retire_duplicate_sales_role._target_for_roles({"Sales", "CRM Data Steward"}),
		)
		self.assertIsNone(retire_duplicate_sales_role._target_for_roles({"Sales", "Custom Role"}))

	def test_forward_patch_migrates_users_and_cleans_runtime_grants(self):
		users = [
			"sales@example.com",
			"sales-alias@example.com",
			"mixed@example.com",
			"system@example.com",
		]
		roles = {
			"sales@example.com": ["Sales"],
			"sales-alias@example.com": ["Sales", "Sales User"],
			"mixed@example.com": ["Sales", "Sales Manager"],
			"system@example.com": ["Sales", "System Manager"],
		}
		docs = {
			user: SimpleNamespace(
				roles=[SimpleNamespace(role=role) for role in user_roles],
				set=lambda field, value, user=user: setattr(docs[user], field, value),
				save=lambda **kwargs: None,
			)
			for user, user_roles in roles.items()
		}

		with (
			patch.object(retire_duplicate_sales_role.frappe, "get_all", return_value=users) as get_all,
			patch.object(retire_duplicate_sales_role.frappe, "get_roles", side_effect=roles.__getitem__),
			patch.object(retire_duplicate_sales_role.frappe, "get_doc", side_effect=lambda doctype, user: docs[user]),
			patch.object(retire_duplicate_sales_role, "set_canonical_crm_profile") as set_profile,
			patch.object(retire_duplicate_sales_role, "apply_managed_docperms") as apply_docperms,
			patch.object(retire_duplicate_sales_role.frappe.db, "delete") as delete,
			patch.object(retire_duplicate_sales_role.frappe, "logger") as logger,
			patch.object(retire_duplicate_sales_role.frappe, "clear_cache") as clear_cache,
		):
			result = retire_duplicate_sales_role.execute()

		self.assertEqual(
			result,
			{
				"migrated": ["sales@example.com", "sales-alias@example.com"],
				"conflicts": ["mixed@example.com", "system@example.com"],
			},
		)
		get_all.assert_called_once_with("User", pluck="name")
		self.assertEqual(set_profile.call_count, 2)
		self.assertTrue(all(call.args[1] == "Sale" for call in set_profile.call_args_list))
		self.assertEqual(docs["sales@example.com"].roles, [])
		self.assertEqual([row.role for row in docs["sales-alias@example.com"].roles], ["Sales User"])
		apply_docperms.assert_called_once_with()
		delete.assert_called_once_with(
			"CRM AI Capability Grant",
			{"parent": "Sales", "parenttype": "Role", "parentfield": "custom_ai_capability_grants"},
		)
		logger.return_value.warning.assert_called_once_with(
			"retire_duplicate_sales_role conflicts=%s", "mixed@example.com,system@example.com"
		)
		clear_cache.assert_called_once_with()

	def test_forward_patch_rolls_back_when_runtime_cleanup_fails(self):
		with (
			patch.object(retire_duplicate_sales_role.frappe, "get_all", return_value=[]),
			patch.object(retire_duplicate_sales_role, "apply_managed_docperms", side_effect=RuntimeError("boom")),
			patch.object(retire_duplicate_sales_role.frappe.db, "savepoint") as savepoint,
			patch.object(retire_duplicate_sales_role.frappe.db, "rollback") as rollback,
		):
			with self.assertRaisesRegex(RuntimeError, "boom"):
				retire_duplicate_sales_role.execute()

		savepoint.assert_called_once_with("retire_duplicate_sales_role")
		rollback.assert_called_once_with(save_point="retire_duplicate_sales_role")
