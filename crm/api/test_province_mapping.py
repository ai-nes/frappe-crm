import json

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.province_mapping import import_mapping


class TestImportMappingPermissions(FrappeTestCase):
	def setUp(self):
		self.user = "_test_pm_unauthorized@example.com"
		if not frappe.db.exists("User", self.user):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": self.user,
					"first_name": "PM Unauthorized",
					"send_welcome_email": 0,
					"roles": [{"role": "Sale"}],
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_import_denies_user_without_system_manager_or_administrator_role(self):
		# frappe.only_for() short-circuits while frappe.flags.in_test is set, so the
		# permission check must be exercised with it temporarily disabled.
		frappe.set_user(self.user)
		frappe.flags.in_test = False
		try:
			self.assertRaises(frappe.PermissionError, import_mapping, [])
		finally:
			frappe.flags.in_test = True


class TestImportMapping(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for code, name in (("_TESTPMA", "_Test PM Province A"), ("_TESTPMB", "_Test PM Province B")):
			if not frappe.db.exists("CRM Province", name):
				frappe.get_doc(
					{
						"doctype": "CRM Province",
						"province_code": code,
						"province_name": name,
					}
				).insert(ignore_permissions=True)

	def tearDown(self):
		for name in frappe.db.get_all(
			"CRM Province Mapping", filters={"old_province": ["like", "_Test PM%"]}, pluck="name"
		):
			frappe.delete_doc("CRM Province Mapping", name, force=True)
		for name in ("_Test PM Province A", "_Test PM Province B"):
			if frappe.db.exists("CRM Province", name):
				frappe.delete_doc("CRM Province", name, force=True)

	def test_import_creates_mapping(self):
		result = import_mapping(
			[{"old_province": "_Test PM Province A", "new_province": "_Test PM Merged"}]
		)
		self.assertIn("_Test PM Province A", result["created"])
		self.assertEqual(result["skipped"], [])

		mapping = frappe.get_doc("CRM Province Mapping", "_Test PM Province A")
		self.assertEqual(mapping.new_province, "_Test PM Merged")

	def test_import_accepts_json_string(self):
		rows = json.dumps([{"old_province": "_Test PM Province A", "new_province": "_Test PM Merged"}])
		result = import_mapping(rows)
		self.assertIn("_Test PM Province A", result["created"])

	def test_import_upserts_existing_mapping(self):
		import_mapping([{"old_province": "_Test PM Province A", "new_province": "_Test PM Merged v1"}])
		result = import_mapping(
			[{"old_province": "_Test PM Province A", "new_province": "_Test PM Merged v2"}]
		)
		self.assertIn("_Test PM Province A", result["created"])
		self.assertEqual(
			frappe.db.count("CRM Province Mapping", {"old_province": "_Test PM Province A"}), 1
		)
		mapping = frappe.get_doc("CRM Province Mapping", "_Test PM Province A")
		self.assertEqual(mapping.new_province, "_Test PM Merged v2")

	def test_import_trims_new_province_whitespace(self):
		import_mapping(
			[{"old_province": "_Test PM Province A", "new_province": "  _Test PM Merged  "}]
		)
		mapping = frappe.get_doc("CRM Province Mapping", "_Test PM Province A")
		self.assertEqual(mapping.new_province, "_Test PM Merged")

	def test_import_skips_missing_fields(self):
		result = import_mapping(
			[
				{"old_province": "_Test PM Province B"},
				{"new_province": "_Test PM Merged"},
				{},
			]
		)
		self.assertEqual(result["created"], [])
		self.assertEqual(len(result["skipped"]), 3)

	def test_import_skips_nonexistent_province(self):
		result = import_mapping(
			[{"old_province": "_Test PM Nonexistent", "new_province": "_Test PM Merged"}]
		)
		self.assertEqual(result["created"], [])
		self.assertEqual(len(result["skipped"]), 1)
		self.assertFalse(frappe.db.exists("CRM Province Mapping", "_Test PM Nonexistent"))

	def test_import_handles_mixed_valid_and_invalid_rows(self):
		result = import_mapping(
			[
				{"old_province": "_Test PM Province A", "new_province": "_Test PM Merged"},
				{"old_province": "_Test PM Nonexistent", "new_province": "_Test PM Merged"},
				{"old_province": "_Test PM Province B", "new_province": ""},
			]
		)
		self.assertEqual(result["created"], ["_Test PM Province A"])
		self.assertEqual(len(result["skipped"]), 2)
