from types import SimpleNamespace
from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.patches.v1_0 import audit_canonical_crm_profiles


class TestAuditCanonicalCrmProfiles(FrappeTestCase):
	def test_audit_reports_policy_states_without_writing(self):
		users = [
			SimpleNamespace(name="sales@example.com"),
			SimpleNamespace(name="alias@example.com"),
			SimpleNamespace(name="same-domain-mixed@example.com"),
			SimpleNamespace(name="system-mixed@example.com"),
			SimpleNamespace(name="mixed@example.com"),
		]
		roles = {
			"sales@example.com": ["Sale"],
			"alias@example.com": ["Sales User"],
			"same-domain-mixed@example.com": ["Sales Manager", "Sales User"],
			"system-mixed@example.com": ["System Manager", "Sales Manager", "Sales User"],
			"mixed@example.com": ["Sale", "Marketing"],
		}
		with (
			patch.object(audit_canonical_crm_profiles.frappe, "get_all", return_value=users),
			patch.object(audit_canonical_crm_profiles.frappe, "get_roles", side_effect=roles.__getitem__),
			patch.object(audit_canonical_crm_profiles.frappe.db, "exists", return_value=True) as exists,
		):
			report = audit_canonical_crm_profiles.execute()

		self.assertEqual(
			report["counts"],
			{"alias": 0, "canonical": 2, "missing_staff": 0, "mixed_profile": 1, "unmapped": 2},
		)
		self.assertEqual(report["users"]["mixed_profile"], ["mixed@example.com"])
		self.assertTrue(report["generated_at"])
		exists.assert_called()
