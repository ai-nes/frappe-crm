import json
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.role_policy import managed_docperm_rows
from crm.patches.v1_0.setup_crm_permissions import DOCTYPE_PERMS


class TestSetupCrmPermissions(FrappeTestCase):
	def test_permissions_are_emitted_from_the_canonical_policy_matrix(self):
		student_permissions = {permission["role"]: permission for permission in DOCTYPE_PERMS["CRM Student"]}

		self.assertEqual(student_permissions["Sale"], {"role": "Sale", "read": 1, "write": 1, "create": 1})
		self.assertEqual(student_permissions["Lead Sales"], {"role": "Lead Sales", "read": 1, "write": 1, "create": 1})
		self.assertNotIn("CRM Data Steward", student_permissions)

	def test_managed_json_fixtures_match_the_canonical_policy(self):
		for doctype, permissions in managed_docperm_rows().items():
			with self.subTest(doctype=doctype):
				scrubbed = frappe.scrub(doctype)
				path = Path(__file__).parents[2] / "fcrm" / "doctype" / scrubbed / f"{scrubbed}.json"
				fixture = json.loads(path.read_text(encoding="utf-8"))
				expected = [dict(sorted(permission.items())) for permission in permissions]
				self.assertEqual(fixture["permissions"], expected)
