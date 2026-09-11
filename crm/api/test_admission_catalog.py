from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.api import admission_catalog


class FakeDocument:
	def __init__(self, **values):
		self.values = values
		self.permission_calls = []
		self.insert_calls = 0
		self.save_calls = 0
		self.delete_calls = 0

	def get(self, fieldname, default=None):
		return self.values.get(fieldname, default)

	def set(self, fieldname, value):
		self.values[fieldname] = value

	def check_permission(self, permission_type):
		self.permission_calls.append(permission_type)

	def insert(self):
		self.insert_calls += 1

	def save(self):
		self.save_calls += 1

	def delete(self):
		self.delete_calls += 1


class TestAdmissionCatalog(TestCase):
	def setUp(self):
		self.session = SimpleNamespace(user="Administrator")
		self.session_patch = patch.object(admission_catalog.frappe, "session", self.session)
		self.session_patch.start()

	def tearDown(self):
		self.session_patch.stop()

	def test_list_document_types_maps_payload_and_filters_archived(self):
		rows = [
			{
				"name": "DOC-001",
				"code": "PASSPORT",
				"label": "Passport",
				"category": "identity",
				"description": "Identity document",
				"conditional_key": "passport",
				"status": "Archived",
				"is_active": 0,
				"modified": "2026-09-11 08:00:00",
			}
		]
		with patch.object(admission_catalog.frappe, "get_list", return_value=rows) as get_list:
			result = admission_catalog.list_admission_document_types(" passport ")

		self.assertEqual(result["documentTypes"][0]["id"], "DOC-001")
		self.assertEqual(result["documentTypes"][0]["name"], "Passport")
		self.assertFalse(result["documentTypes"][0]["isActive"])
		self.assertEqual(get_list.call_args.kwargs["filters"], {"status": ["in", ["Active", "Archived"]]})
		self.assertEqual(
			get_list.call_args.kwargs["or_filters"],
			[
				["name", "like", "%passport%"],
				["code", "like", "%passport%"],
				["label", "like", "%passport%"],
				["category", "like", "%passport%"],
			],
		)

	def test_list_methods_excludes_disabled_rows_when_requested(self):
		rows = [
			{
				"name": "THPT_SCORE",
				"code": "THPT_SCORE",
				"display_name": "Thi tốt nghiệp THPT",
				"description": None,
				"enabled": 1,
				"sort_order": 10,
				"modified": "2026-09-11 08:00:00",
			}
		]
		with patch.object(admission_catalog.frappe, "get_list", return_value=rows) as get_list:
			result = admission_catalog.list_admission_methods(include_disabled=False)

		self.assertEqual(result["methods"][0]["name"], "Thi tốt nghiệp THPT")
		self.assertEqual(result["methods"][0]["sortOrder"], 10)
		self.assertEqual(get_list.call_args.kwargs["filters"], {"enabled": 1})

	def test_create_and_update_normalize_aliases_and_use_exact_permissions(self):
		doc = FakeDocument(
			name="DOC-001",
			code="",
			label="",
			category="identity",
			description=None,
			conditional_key=None,
			status="Active",
			is_active=1,
			modified="2026-09-11 08:00:00",
		)
		with (
			patch.object(admission_catalog.frappe, "new_doc", return_value=doc),
			patch.object(admission_catalog.frappe.db, "exists", return_value=False),
		):
			created = admission_catalog.create_admission_document_type(
				{
					"code": " passport ",
					"name": "  Passport  ",
					"category": " Identity ",
					"conditionalKey": "  passport  ",
				}
			)

		self.assertEqual(doc.values["code"], "PASSPORT")
		self.assertEqual(doc.values["label"], "Passport")
		self.assertEqual(doc.values["conditional_key"], "passport")
		self.assertEqual(doc.permission_calls, ["create"])
		self.assertEqual(doc.insert_calls, 1)
		self.assertEqual(created["code"], "PASSPORT")

		doc.values["modified"] = "2026-09-11 09:00:00"
		with patch.object(admission_catalog.frappe, "get_doc", return_value=doc):
			updated = admission_catalog.update_admission_document_type(
				"DOC-001",
				{"code": " passport ", "name": " Updated passport "},
				expected_modified="2026-09-11 09:00:00",
			)

		self.assertEqual(doc.values["label"], "Updated passport")
		self.assertEqual(doc.permission_calls, ["create", "write"])
		self.assertEqual(doc.save_calls, 1)
		self.assertEqual(updated["name"], "Updated passport")

	def test_duplicate_and_invalid_input_are_validation_errors(self):
		doc = FakeDocument(name="THPT_SCORE", modified="2026-09-11 08:00:00")
		with (
			patch.object(admission_catalog.frappe, "new_doc", return_value=doc),
			patch.object(admission_catalog.frappe.db, "exists", return_value=True),
		):
			with self.assertRaises(frappe.DuplicateEntryError):
				admission_catalog.create_admission_method(
					{"code": " thpt_score ", "display_name": "THPT", "sortOrder": "10"}
				)

		with self.assertRaises(frappe.ValidationError):
			admission_catalog.create_admission_method(
				{"code": "NEW_METHOD", "display_name": "New", "sort_order": "10.5"}
			)
		self.assertEqual(doc.insert_calls, 0)

	def test_stale_update_is_rejected_before_save(self):
		doc = FakeDocument(
			name="THPT_SCORE",
			code="THPT_SCORE",
			display_name="THPT",
			enabled=1,
			sort_order=10,
			modified="2026-09-11 10:00:00",
		)
		with patch.object(admission_catalog.frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.ValidationError):
				admission_catalog.update_admission_method(
					"THPT_SCORE",
					{"name": "Updated"},
					expected_modified="2026-09-11 09:00:00",
				)

		self.assertEqual(doc.permission_calls, ["write"])
		self.assertEqual(doc.save_calls, 0)

	def test_code_is_immutable_on_update(self):
		doc = FakeDocument(
			name="THPT_SCORE",
			code="THPT_SCORE",
			display_name="THPT",
			enabled=1,
			sort_order=10,
			modified="2026-09-11 10:00:00",
		)
		with patch.object(admission_catalog.frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.PermissionError):
				admission_catalog.update_admission_method(
					"THPT_SCORE",
					{"code": "OTHER_METHOD"},
					expected_modified="2026-09-11 10:00:00",
				)

		self.assertEqual(doc.save_calls, 0)

	def test_mutations_require_authentication_and_doctype_permission(self):
		self.session.user = "Guest"
		with self.assertRaises(frappe.AuthenticationError):
			admission_catalog.create_admission_method({"code": "NEW", "name": "New"})

		self.session.user = "Administrator"
		doc = FakeDocument(name="THPT_SCORE", code="THPT_SCORE", modified="2026-09-11 08:00:00")
		with (
			patch.object(admission_catalog.frappe, "get_doc", return_value=doc),
			patch.object(admission_catalog.frappe.db, "exists", return_value=False),
		):
			result = admission_catalog.delete_admission_method(
				"THPT_SCORE", expected_modified="2026-09-11 08:00:00"
			)

		self.assertEqual(result, {"deleted": "THPT_SCORE"})
		self.assertEqual(doc.permission_calls, ["delete"])
		self.assertEqual(doc.delete_calls, 1)

	def test_referenced_document_type_cannot_be_deleted(self):
		doc = FakeDocument(name="DOC-001", code="PASSPORT", modified="2026-09-11 08:00:00")

		def exists(doctype, filters):
			return doctype == "CRM Student Document"

		with (
			patch.object(admission_catalog.frappe, "get_doc", return_value=doc),
			patch.object(admission_catalog.frappe.db, "exists", side_effect=exists),
		):
			with self.assertRaises(frappe.ValidationError):
				admission_catalog.delete_admission_document_type(
					"DOC-001", expected_modified="2026-09-11 08:00:00"
				)

		self.assertEqual(doc.delete_calls, 0)

	def test_referenced_admission_method_cannot_be_deleted(self):
		doc = FakeDocument(name="THPT_SCORE", code="THPT_SCORE", modified="2026-09-11 08:00:00")

		def exists(doctype, filters):
			return doctype == "CRM Admission Offering"

		with (
			patch.object(admission_catalog.frappe, "get_doc", return_value=doc),
			patch.object(admission_catalog.frappe.db, "exists", side_effect=exists),
		):
			with self.assertRaises(frappe.ValidationError):
				admission_catalog.delete_admission_method(
					"THPT_SCORE", expected_modified="2026-09-11 08:00:00"
				)

		self.assertEqual(doc.delete_calls, 0)
