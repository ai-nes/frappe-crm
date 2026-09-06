from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.patches.v1_0 import backfill_canonical_role_targets


class TestBackfillCanonicalRoleTargets(FrappeTestCase):
	def test_backfill_moves_only_unambiguous_source_roles(self):
		users = ["sales-user@example.com", "lead@example.com", "director@example.com", "mixed@example.com", "system@example.com"]
		roles = {
			"sales-user@example.com": ["Sales User"],
			"lead@example.com": ["Sales Manager"],
			"director@example.com": ["Giám đốc Tuyển sinh"],
			"mixed@example.com": ["Sales User", "Sales Manager"],
			"system@example.com": ["System Manager", "Sales User"],
		}
		with (
			patch.object(backfill_canonical_role_targets.frappe, "get_all", return_value=users),
			patch.object(backfill_canonical_role_targets.frappe, "get_roles", side_effect=roles.__getitem__),
			patch.object(
				backfill_canonical_role_targets.frappe,
				"get_doc",
				side_effect=lambda doctype, user: SimpleNamespace(save=lambda **kwargs: None),
			),
			patch.object(backfill_canonical_role_targets, "set_canonical_crm_profile") as set_profile,
		):
			result = backfill_canonical_role_targets.execute()

		self.assertEqual(result, {"migrated": users[:3], "conflicts": users[3:]})
		self.assertEqual(
			[call.args[1] for call in set_profile.call_args_list],
			["Sale", "Lead Sale", "Admissions Director"],
		)
