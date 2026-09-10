from pathlib import Path
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.role_policy import DESK_MANAGEMENT_ROLE_NAMES
from crm.patches.v1_0 import restore_desk_management_roles


class TestRestoreDeskManagementRoles(FrappeTestCase):
	def test_patch_is_registered_after_the_role_policy(self):
		patches = (Path(__file__).parents[2] / "patches.txt").read_text(encoding="utf-8").splitlines()
		self.assertLess(
			patches.index("crm.patches.v1_0.apply_role_policy"),
			patches.index("crm.patches.v1_0.restore_desk_management_roles"),
		)

	def test_patch_provisions_missing_roles_and_assignments_for_system_managers(self):
		with (
			patch.object(restore_desk_management_roles, "create_roles") as create_roles,
			patch.object(restore_desk_management_roles.frappe, "get_all", return_value=["admin@example.com"]),
			patch.object(restore_desk_management_roles.frappe.db, "exists", return_value=None),
			patch.object(restore_desk_management_roles.frappe, "get_doc") as get_doc,
			patch.object(restore_desk_management_roles.frappe, "clear_cache") as clear_cache,
		):
			restore_desk_management_roles.execute()

		create_roles.assert_called_once_with(DESK_MANAGEMENT_ROLE_NAMES)
		self.assertEqual(get_doc.call_count, len(DESK_MANAGEMENT_ROLE_NAMES))
		self.assertEqual(
			{entry.args[0]["role"] for entry in get_doc.call_args_list}, set(DESK_MANAGEMENT_ROLE_NAMES)
		)
		clear_cache.assert_called_once_with()

	def test_patch_is_idempotent_when_assignments_already_exist(self):
		with (
			patch.object(restore_desk_management_roles, "create_roles"),
			patch.object(restore_desk_management_roles.frappe, "get_all", return_value=["admin@example.com"]),
			patch.object(restore_desk_management_roles.frappe.db, "exists", return_value="HAS-ROLE-0001"),
			patch.object(restore_desk_management_roles.frappe, "get_doc") as get_doc,
		):
			restore_desk_management_roles.execute()

		get_doc.assert_not_called()

	def test_patch_rolls_back_without_clearing_cache_when_provisioning_fails(self):
		with (
			patch.object(restore_desk_management_roles, "create_roles", side_effect=RuntimeError("boom")),
			patch.object(restore_desk_management_roles.frappe.db, "savepoint") as savepoint,
			patch.object(restore_desk_management_roles.frappe.db, "rollback") as rollback,
			patch.object(restore_desk_management_roles.frappe, "clear_cache") as clear_cache,
		):
			with self.assertRaisesRegex(RuntimeError, "boom"):
				restore_desk_management_roles.execute()

		savepoint.assert_called_once_with("restore_desk_management_roles")
		rollback.assert_called_once_with(save_point="restore_desk_management_roles")
		clear_cache.assert_not_called()
