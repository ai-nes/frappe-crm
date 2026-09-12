import json
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.role_policy import _hardcoded_managed_docperm_rows, managed_docperm_rows
from crm.patches.v1_0 import setup_crm_permissions
from crm.patches.v1_0.setup_crm_permissions import get_doctype_perms


class TestSetupCrmPermissions(FrappeTestCase):
	def test_permissions_are_emitted_from_the_canonical_policy_matrix(self):
		student_permissions = {
			permission["role"]: permission for permission in get_doctype_perms()["CRM Lead"]
		}

		self.assertEqual(student_permissions["Sale"], {"role": "Sale", "read": 1, "write": 1, "create": 1})
		self.assertEqual(
			student_permissions["Lead Sale"],
			{"role": "Lead Sale", "read": 1, "write": 1, "create": 1, "delete": 1},
		)
		self.assertNotIn("CRM Data Steward", student_permissions)

	def test_lead_sale_can_create_and_update_student_payment_account(self):
		permissions = {
			permission["role"]: permission
			for permission in _hardcoded_managed_docperm_rows()["CRM Student Payment Account"]
		}

		self.assertEqual(
			permissions["Lead Sale"],
			{"create": 1, "read": 1, "role": "Lead Sale", "write": 1},
		)

	def test_managed_json_fixtures_match_the_canonical_policy(self):
		for doctype, permissions in managed_docperm_rows().items():
			with self.subTest(doctype=doctype):
				scrubbed = frappe.scrub(doctype)
				path = Path(__file__).parents[2] / "fcrm" / "doctype" / scrubbed / f"{scrubbed}.json"
				fixture = json.loads(path.read_text(encoding="utf-8"))
				expected = [dict(sorted(permission.items())) for permission in permissions]
				self.assertEqual(fixture["permissions"], expected)


class TestApplyManagedDocpermsIdempotentSync(FrappeTestCase):
	"""Phase 6: `apply_managed_docperms` must be idempotent and must clean up
	only the specific `(doctype, role)` pairs it previously synced -- never a
	bulk role-set filter, and never a row it never wrote itself.

	These tests exercise the real DocPerm table (not mocks) so the DB-diffing
	logic in `_existing_docperm_flags`/`_permission_matches` is genuinely
	verified, while confining every write to a scratch role that no real user
	holds.
	"""

	TEST_ROLE = "_Test Docperm Sync Role"
	TEST_DOCTYPE = "CRM Lead"
	OTHER_DOCTYPE = "CRM Lost Reason"

	def setUp(self):
		if not frappe.db.exists("Role", self.TEST_ROLE):
			frappe.get_doc({"doctype": "Role", "role_name": self.TEST_ROLE, "desk_access": 0}).insert(
				ignore_permissions=True
			)
		self._clear_test_docperm_rows()
		frappe.db.set_single_value("FCRM Settings", "managed_docperm_sync_state", None)

	def tearDown(self):
		self._clear_test_docperm_rows()
		frappe.db.set_single_value("FCRM Settings", "managed_docperm_sync_state", None)
		frappe.db.delete("Role", {"role_name": self.TEST_ROLE})

	def _clear_test_docperm_rows(self):
		frappe.db.delete(
			"DocPerm",
			{
				"parenttype": "DocType",
				"role": self.TEST_ROLE,
				"parent": ["in", [self.TEST_DOCTYPE, self.OTHER_DOCTYPE]],
			},
		)

	def _docperm_flags(self, doctype):
		return setup_crm_permissions._existing_docperm_flags(doctype, self.TEST_ROLE)

	def _run_with_desired(self, desired):
		with patch.object(setup_crm_permissions, "get_doctype_perms", return_value=desired):
			setup_crm_permissions.apply_managed_docperms()

	def test_first_run_creates_the_managed_row(self):
		desired = {self.TEST_DOCTYPE: [{"role": self.TEST_ROLE, "read": 1, "write": 1}]}

		self.assertIsNone(self._docperm_flags(self.TEST_DOCTYPE))
		self._run_with_desired(desired)

		flags = self._docperm_flags(self.TEST_DOCTYPE)
		self.assertIsNotNone(flags)
		self.assertTrue(flags["read"])
		self.assertTrue(flags["write"])
		self.assertFalse(flags["create"])

	def test_repeat_run_with_no_changes_is_a_no_op_and_preserves_hand_edits_outside_the_managed_set(self):
		desired = {self.TEST_DOCTYPE: [{"role": self.TEST_ROLE, "read": 1, "write": 1}]}
		self._run_with_desired(desired)

		# A hand-added row for a role/doctype pair this patch never manages.
		frappe.get_doc(
			{
				"doctype": "DocPerm",
				"parent": self.OTHER_DOCTYPE,
				"parenttype": "DocType",
				"parentfield": "permissions",
				"permlevel": 0,
				"role": self.TEST_ROLE,
				"read": 1,
			}
		).insert(ignore_permissions=True)

		with (
			patch.object(setup_crm_permissions.frappe.db, "delete") as delete,
			patch.object(setup_crm_permissions.frappe, "get_doc", wraps=frappe.get_doc) as get_doc,
		):
			self._run_with_desired(desired)

		# `_save_synced_pairs` writes via `frappe.db.set_single_value`, which
		# itself issues an unrelated `Singles` delete on every run -- only a
		# `DocPerm` delete would indicate an (unwanted) row replacement here.
		docperm_deletes = [call for call in delete.call_args_list if call.args[0] == "DocPerm"]
		self.assertEqual(docperm_deletes, [])
		docperm_inserts = [
			call
			for call in get_doc.call_args_list
			if call.args and isinstance(call.args[0], dict) and call.args[0].get("doctype") == "DocPerm"
		]
		self.assertEqual(docperm_inserts, [])
		self.assertIsNotNone(self._docperm_flags(self.OTHER_DOCTYPE))

	def test_adding_a_managed_doctype_only_writes_the_new_pair(self):
		desired = {self.TEST_DOCTYPE: [{"role": self.TEST_ROLE, "read": 1}]}
		self._run_with_desired(desired)
		existing_flags_before = self._docperm_flags(self.TEST_DOCTYPE)

		expanded = {
			self.TEST_DOCTYPE: [{"role": self.TEST_ROLE, "read": 1}],
			self.OTHER_DOCTYPE: [{"role": self.TEST_ROLE, "read": 1, "write": 1}],
		}
		self._run_with_desired(expanded)

		self.assertEqual(self._docperm_flags(self.TEST_DOCTYPE), existing_flags_before)
		new_flags = self._docperm_flags(self.OTHER_DOCTYPE)
		self.assertIsNotNone(new_flags)
		self.assertTrue(new_flags["write"])

	def test_removing_a_managed_doctype_cleans_up_only_that_row(self):
		desired = {
			self.TEST_DOCTYPE: [{"role": self.TEST_ROLE, "read": 1}],
			self.OTHER_DOCTYPE: [{"role": self.TEST_ROLE, "read": 1}],
		}
		self._run_with_desired(desired)
		self.assertIsNotNone(self._docperm_flags(self.TEST_DOCTYPE))
		self.assertIsNotNone(self._docperm_flags(self.OTHER_DOCTYPE))

		shrunk = {self.TEST_DOCTYPE: [{"role": self.TEST_ROLE, "read": 1}]}
		self._run_with_desired(shrunk)

		self.assertIsNotNone(self._docperm_flags(self.TEST_DOCTYPE))
		self.assertIsNone(self._docperm_flags(self.OTHER_DOCTYPE))
