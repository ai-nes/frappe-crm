from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.role_policy import PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY, CRM_POLICY_ROLE_NAMES
from crm.patches.v1_0 import apply_role_policy, setup_crm_permissions
from crm.patches.v1_0.setup_crm_permissions import MANAGED_DOCPERM_ROLE_NAMES


class TestApplyPhase2RolePolicy(FrappeTestCase):
	def test_forward_patch_is_registered_after_the_existing_role_contract_patch(self):
		patches = (Path(__file__).parents[2] / "patches.txt").read_text(encoding="utf-8").splitlines()
		self.assertLess(
			patches.index("crm.patches.v1_0.apply_canonical_crm_role_contract"),
			patches.index("crm.patches.v1_0.apply_role_policy"),
		)

	def test_forward_patch_uses_only_database_adapters(self):
		with (
			patch.object(apply_role_policy, "create_roles") as create_roles,
			patch.object(apply_role_policy, "apply_managed_docperms") as apply_docperms,
			patch.object(apply_role_policy.frappe, "clear_cache") as clear_cache,
		):
			apply_role_policy.execute()

		create_roles.assert_called_once_with(CRM_POLICY_ROLE_NAMES)
		apply_docperms.assert_called_once_with()
		clear_cache.assert_called_once_with()

	def test_forward_patch_rolls_back_its_database_adapter_on_failure(self):
		with (
			patch.object(apply_role_policy, "create_roles"),
			patch.object(apply_role_policy, "apply_managed_docperms", side_effect=RuntimeError("boom")),
			patch.object(apply_role_policy.frappe.db, "savepoint") as savepoint,
			patch.object(apply_role_policy.frappe.db, "rollback") as rollback,
		):
			with self.assertRaisesRegex(RuntimeError, "boom"):
				apply_role_policy.execute()

		savepoint.assert_called_once_with("phase2_role_policy")
		rollback.assert_called_once_with(save_point="phase2_role_policy")

	def test_permission_adapter_never_touches_legacy_untouched_doctypes(self):
		# Force the hardcoded matrix: `get_doctype_perms()` otherwise reads live
		# `CRM Permission Profile` records via `frappe.get_doc`, which this test
		# also mocks below -- letting the loader hit that mock would try to
		# cache a MagicMock and blow up in `frappe.cache().set_value`.
		#
		# `_permission_matches` is also forced to `False` so every managed pair
		# is treated as a first-run write regardless of whatever DocPerm rows
		# already exist on the test site -- the idempotent sync (Phase 6) would
		# otherwise skip writes for pairs already in sync, leaving nothing for
		# this test to observe.
		frappe.conf[PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY] = 1
		try:
			with (
				patch.object(setup_crm_permissions, "_permission_matches", return_value=False),
				patch.object(setup_crm_permissions, "_load_previously_synced_pairs", return_value=set()),
				patch.object(setup_crm_permissions, "_save_synced_pairs"),
				patch.object(setup_crm_permissions.frappe.db, "delete") as delete,
				patch.object(setup_crm_permissions.frappe, "get_doc") as get_doc,
			):
				get_doc.return_value.insert.return_value = None
				setup_crm_permissions.apply_managed_docperms()
		finally:
			frappe.conf.pop(PERMISSION_PROFILE_KILL_SWITCH_CONFIG_KEY, None)

		managed_doctypes = {call.args[1]["parent"] for call in delete.call_args_list}
		self.assertIn("CRM Student", managed_doctypes)
		self.assertNotIn("CRM Staff", managed_doctypes)
		self.assertIn("CRM Recommendation", managed_doctypes)
		for call in delete.call_args_list:
			self.assertIn(call.args[1]["role"], MANAGED_DOCPERM_ROLE_NAMES)
