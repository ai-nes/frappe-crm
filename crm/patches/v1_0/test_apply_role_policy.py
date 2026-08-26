from pathlib import Path
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.role_policy import CRM_POLICY_ROLE_NAMES
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
		with (
			patch.object(setup_crm_permissions.frappe.db, "delete") as delete,
			patch.object(setup_crm_permissions.frappe, "get_doc") as get_doc,
		):
			get_doc.return_value.insert.return_value = None
			setup_crm_permissions.apply_managed_docperms()

		managed_doctypes = {call.args[1]["parent"] for call in delete.call_args_list}
		self.assertIn("CRM Student", managed_doctypes)
		self.assertNotIn("CRM Staff", managed_doctypes)
		self.assertIn("CRM Recommendation", managed_doctypes)
		for call in delete.call_args_list:
			self.assertEqual(set(call.args[1]["role"][1]), set(MANAGED_DOCPERM_ROLE_NAMES))
