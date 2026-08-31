import json

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.province_mapping import import_mapping


class TestImportMapping(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		for code, name in (("_TESTPMA", "_Test PM Province A"), ("_TESTPMB", "_Test PM Province B")):
			if not frappe.db.exists("CRM Province", name):
				frappe.get_doc({"doctype": "CRM Province", "province_code": code, "province_name": name}).insert(ignore_permissions=True)

	def tearDown(self):
		for name in ("_Test PM Province A", "_Test PM Province B"):
			if frappe.db.exists("CRM Province", name):
				frappe.delete_doc("CRM Province", name, force=True)

	def test_import_creates_child_mapping(self):
		result = import_mapping([{"old_province": "_Test PM Province A", "new_province": "_Test PM Province B"}])
		self.assertEqual(result["created"], ["_Test PM Province A"])
		self.assertEqual(frappe.db.count("CRM Province Former Name", {"parent": "_Test PM Province B", "former_name": "_Test PM Province A"}), 1)

	def test_import_is_idempotent_and_accepts_json(self):
		row = json.dumps([{"old_province": "_Test PM Province A", "new_province": " _Test PM Province B "}])
		import_mapping(row)
		import_mapping(row)
		self.assertEqual(frappe.db.count("CRM Province Former Name", {"parent": "_Test PM Province B", "former_name": "_Test PM Province A"}), 1)

	def test_import_skips_invalid_rows(self):
		result = import_mapping([
			{"old_province": "_Test PM Missing", "new_province": "_Test PM Province B"},
			{"old_province": "_Test PM Province A"},
			{"new_province": "_Test PM Province B"},
		])
		self.assertEqual(result["created"], [])
		self.assertEqual(len(result["skipped"]), 3)
