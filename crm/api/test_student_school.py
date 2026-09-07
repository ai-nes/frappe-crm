import json
from unittest import TestCase
from unittest.mock import Mock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_school import (
	create_school,
	create_student,
	delete_school,
	delete_student,
	get_field_options,
	get_school,
	get_schools,
	get_student,
	update_school,
	update_student,
)


class _FakeDocument:
	def __init__(self, doctype, name):
		self.doctype = doctype
		self.name = name
		self.values = {}
		self.check_permission_calls = []
		self.save_calls = 0
		self.insert_calls = 0

	def check_permission(self, permission_type):
		self.check_permission_calls.append(permission_type)

	def set(self, fieldname, value):
		self.values[fieldname] = value

	def get(self, fieldname):
		return self.values.get(fieldname)

	def save(self):
		self.save_calls += 1

	def insert(self):
		self.insert_calls += 1
		return self


class TestStudentSchoolApi(TestCase):
	def test_create_student_returns_created_fields(self):
		doc = _FakeDocument("CRM Lead", "STU-NEW-001")
		with patch.object(frappe, "new_doc", return_value=doc):
			result = create_student({"student_name": "Nguyen Van B", "phone": "0900000001"})

		self.assertEqual(
			result,
			{
				"doctype": "CRM Lead",
				"name": "STU-NEW-001",
				"created_fields": {"student_name": "Nguyen Van B", "phone": "0900000001"},
			},
		)
		self.assertEqual(doc.check_permission_calls, ["create"])
		self.assertEqual(doc.insert_calls, 1)

	def test_create_school_accepts_json_and_requires_identity_fields(self):
		doc = _FakeDocument("CRM High School", "SCH-NEW-001")
		with patch.object(frappe, "new_doc", return_value=doc):
			result = create_school(
				json.dumps(
					{
						"school_name": "THPT Nguyen Trai",
						"school_code": "NT-001",
						"province": "PROVINCE-001",
						"ward": "WARD-001",
					}
				)
			)

		self.assertEqual(result["doctype"], "CRM High School")
		self.assertEqual(result["name"], "SCH-NEW-001")
		self.assertEqual(result["created_fields"]["school_code"], "NT-001")
		self.assertEqual(doc.check_permission_calls, ["create"])
		self.assertEqual(doc.insert_calls, 1)

	def test_create_rejects_missing_required_fields_before_loading_document(self):
		with patch.object(frappe, "new_doc") as new_doc:
			with self.assertRaises(frappe.ValidationError):
				create_school({"school_name": "THPT Nguyen Trai"})

		new_doc.assert_not_called()

	def test_get_student_returns_only_doctype_list_view_fields(self):
		doc = _FakeDocument("CRM Lead", "STU-GET-001")
		doc.values = {"student_name": "Nguyen Van C", "phone": "0900000002", "email": "c@example.com"}
		meta = Mock(
			fields=[
				Mock(fieldname="student_name", in_list_view=1),
				Mock(fieldname="phone", in_list_view=1),
				Mock(fieldname="email", in_list_view=0),
			]
		)
		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "get_meta", return_value=meta),
		):
			result = get_student(" STU-GET-001 ")

		self.assertEqual(
			result,
			{
				"doctype": "CRM Lead",
				"name": "STU-GET-001",
				"fields": {"student_name": "Nguyen Van C", "phone": "0900000002"},
			},
		)
		self.assertEqual(doc.check_permission_calls, ["read"])

	def test_get_school_uses_read_permission(self):
		doc = _FakeDocument("CRM High School", "SCH-GET-001")
		meta = Mock(fields=[Mock(fieldname="school_name", in_list_view=1)])
		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "get_meta", return_value=meta),
		):
			result = get_school("SCH-GET-001")

		self.assertEqual(result["doctype"], "CRM High School")
		self.assertEqual(result["name"], "SCH-GET-001")
		self.assertEqual(result["fields"], {"school_name": None})
		self.assertEqual(doc.check_permission_calls, ["read"])

	def test_get_schools_filters_by_province_and_ward(self):
		meta = Mock(
			fields=[
				Mock(fieldname="school_name", in_list_view=1),
				Mock(fieldname="school_code", in_list_view=1),
				Mock(fieldname="province", in_list_view=1),
				Mock(fieldname="ward", in_list_view=1),
			]
		)
		rows = [
			{
				"name": "SCHOOL-001",
				"school_name": "THPT Nguyễn Huệ",
				"school_code": "NH-001",
				"province": "PROVINCE-001",
				"ward": "WARD-001",
			}
		]
		with (
			patch.object(frappe, "get_meta", return_value=meta),
			patch.object(frappe, "get_list", return_value=rows) as get_list,
		):
			result = get_schools(province=" PROVINCE-001 ", ward="WARD-001", search="Nguyễn", limit="10")

		self.assertEqual(
			result["filters"], {"province": "PROVINCE-001", "ward": "WARD-001", "search": "Nguyễn"}
		)
		self.assertEqual(result["schools"][0]["name"], "SCHOOL-001")
		self.assertEqual(result["schools"][0]["fields"]["school_name"], "THPT Nguyễn Huệ")
		get_list.assert_called_once_with(
			"CRM High School",
			filters={"province": "PROVINCE-001", "ward": "WARD-001"},
			or_filters=[
				["school_name", "like", "%Nguyễn%"],
				["school_code", "like", "%Nguyễn%"],
			],
			fields=["name", "school_name", "school_code", "province", "ward"],
			order_by="school_name asc, name asc",
			limit_page_length=10,
		)

	def test_get_field_options_reads_select_values_and_applies_search(self):
		meta = Mock(
			fields=[
				Mock(fieldname="school_tier", fieldtype="Select", options="\nA\nB\nC"),
			]
		)
		with patch.object(frappe, "get_meta", return_value=meta):
			result = get_field_options("CRM High School", "school_tier", search="b")

		self.assertEqual(result["fieldtype"], "Select")
		self.assertIsNone(result["target_doctype"])
		self.assertEqual(result["options"], [{"value": "B", "label": "B"}])

	def test_get_field_options_reads_link_values_and_passes_filters(self):
		field = Mock(fieldname="ward", fieldtype="Link", options="CRM Ward")
		source_meta = Mock(fields=[field])
		target_meta = Mock(
			fields=[Mock(fieldname="name"), Mock(fieldname="ward_name"), Mock(fieldname="province")],
			title_field="ward_name",
		)
		rows = [{"name": "WARD-001", "ward_name": "Ward 1"}]
		with (
			patch.object(frappe, "get_meta", side_effect=[source_meta, target_meta]),
			patch.object(frappe, "get_list", return_value=rows) as get_list,
		):
			result = get_field_options(
				"CRM Lead",
				"ward",
				province="PROVINCE-001",
				limit=10,
			)

		self.assertEqual(result["target_doctype"], "CRM Ward")
		self.assertEqual(result["options"], [{"value": "WARD-001", "label": "Ward 1"}])
		get_list.assert_called_once_with(
			"CRM Ward",
			filters={"province": "PROVINCE-001"},
			or_filters=None,
			fields=["name", "ward_name"],
			order_by="ward_name asc, name asc",
			limit_page_length=10,
		)

	def test_get_field_options_rejects_unknown_doctype_and_non_option_field(self):
		with self.assertRaises(frappe.ValidationError):
			get_field_options("CRM Province", "name")

		meta = Mock(fields=[Mock(fieldname="school_name", fieldtype="Data")])
		with patch.object(frappe, "get_meta", return_value=meta):
			with self.assertRaises(frappe.ValidationError):
				get_field_options("CRM High School", "school_name")

	def test_update_student_accepts_json_and_returns_updated_fields(self):
		doc = _FakeDocument("CRM Lead", "STU-001")
		with patch.object(frappe, "get_doc", return_value=doc):
			result = update_student(
				"STU-001",
				json.dumps({"student_name": "Nguyen Van A", "phone": "0900000000"}),
			)

		self.assertEqual(
			result,
			{
				"doctype": "CRM Lead",
				"name": "STU-001",
				"updated_fields": {"student_name": "Nguyen Van A", "phone": "0900000000"},
			},
		)
		self.assertEqual(doc.values, {"student_name": "Nguyen Van A", "phone": "0900000000"})
		self.assertEqual(doc.check_permission_calls, ["write"])
		self.assertEqual(doc.save_calls, 1)

	def test_ctv_sale_can_only_update_note_and_status_fields(self):
		with (
			patch.object(frappe.session, "user", "ctv@example.com"),
			patch.object(frappe, "get_roles", return_value=["CTV Sale"]),
		):
			with self.assertRaises(frappe.PermissionError):
				update_student("STU-001", {"phone": "0900000000"})

	def test_update_school_accepts_partial_dict(self):
		doc = _FakeDocument("CRM High School", "SCH-001")
		with patch.object(frappe, "get_doc", return_value=doc):
			result = update_school(
				" SCH-001 ", {"school_name": "THPT Nguyen Hue", "address": "123 Nguyen Hue"}
			)

		self.assertEqual(result["doctype"], "CRM High School")
		self.assertEqual(result["name"], "SCH-001")
		self.assertEqual(
			result["updated_fields"],
			{"school_name": "THPT Nguyen Hue", "address": "123 Nguyen Hue"},
		)
		self.assertEqual(doc.values, {"school_name": "THPT Nguyen Hue", "address": "123 Nguyen Hue"})

	def test_update_rejects_empty_fields_before_loading_document(self):
		with patch.object(frappe, "get_doc") as get_doc:
			with self.assertRaises(frappe.ValidationError):
				update_student("STU-001", {})

		get_doc.assert_not_called()

	def test_update_rejects_fields_outside_basic_info_allowlist(self):
		with patch.object(frappe, "get_doc") as get_doc:
			with self.assertRaises(frappe.ValidationError):
				update_school("SCH-001", {"school_code": "SCHOOL-001"})

		get_doc.assert_not_called()

	def test_update_uses_document_permission(self):
		doc = Mock()
		doc.check_permission.side_effect = frappe.PermissionError("Not permitted")
		with patch.object(frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.PermissionError):
				update_school("SCH-001", {"school_name": "THPT Nguyen Hue"})

		doc.set.assert_not_called()
		doc.save.assert_not_called()

	def test_update_rejects_malformed_json_fields(self):
		with patch.object(frappe, "get_doc") as get_doc:
			with self.assertRaises(frappe.ValidationError):
				update_student("STU-001", "{invalid-json")

		get_doc.assert_not_called()

	def test_delete_checks_permission_and_returns_deleted_document(self):
		doc = _FakeDocument("CRM Lead", "STU-DELETE-001")
		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "delete_doc") as delete_doc,
		):
			result = delete_student(" STU-DELETE-001 ")

		self.assertEqual(
			result,
			{"doctype": "CRM Lead", "name": "STU-DELETE-001", "deleted": True},
		)
		self.assertEqual(doc.check_permission_calls, ["delete"])
		delete_doc.assert_called_once_with("CRM Lead", "STU-DELETE-001")

	def test_delete_rejects_empty_name_before_loading_document(self):
		with patch.object(frappe, "get_doc") as get_doc:
			with self.assertRaises(frappe.ValidationError):
				delete_school(" ")

		get_doc.assert_not_called()


class TestStudentSchoolApiIntegration(FrappeTestCase):
	def test_get_field_options_returns_provinces_and_wards_filtered_by_province(self):
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		province = frappe.db.get_value("CRM Province", {}, "name")
		if not province:
			frappe.set_user(previous_user)
			self.skipTest("CRM Province fixtures are required")

		try:
			province_options = get_field_options("CRM Lead", "province", limit=5)
			ward_options = get_field_options("CRM Lead", "ward", filters={"province": province}, limit=5)
			self.assertEqual(province_options["target_doctype"], "CRM Province")
			self.assertTrue(province_options["options"])
			self.assertEqual(ward_options["target_doctype"], "CRM Ward")
			for option in ward_options["options"]:
				self.assertEqual(frappe.db.get_value("CRM Ward", option["value"], "province"), province)
		finally:
			frappe.set_user(previous_user)

	def test_create_and_delete_school_through_frappe(self):
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		province = frappe.db.get_value("CRM Province", {}, "name")
		ward = frappe.db.get_value("CRM Ward", {"province": province}, "name") if province else None
		if not province or not ward:
			frappe.set_user(previous_user)
			self.skipTest("CRM Province and CRM Ward fixtures are required")

		created_name = None
		try:
			result = create_school(
				{
					"school_name": "_Create API School",
					"school_code": "_CREATE_API_SCHOOL",
					"province": province,
					"ward": ward,
				}
			)
			created_name = result["name"]
			self.assertTrue(frappe.db.exists("CRM High School", created_name))

			deleted = delete_school(created_name)
			self.assertEqual(deleted, {"doctype": "CRM High School", "name": created_name, "deleted": True})
			self.assertFalse(frappe.db.exists("CRM High School", created_name))
		finally:
			if created_name and frappe.db.exists("CRM High School", created_name):
				frappe.delete_doc("CRM High School", created_name, force=True, ignore_permissions=True)
			frappe.set_user(previous_user)

	def test_update_school_saves_through_frappe_and_enforces_permission(self):
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		province = frappe.db.get_value("CRM Province", {}, "name")
		ward = frappe.db.get_value("CRM Ward", {"province": province}, "name") if province else None
		if not province or not ward:
			frappe.set_user(previous_user)
			self.skipTest("CRM Province and CRM Ward fixtures are required")

		school = frappe.get_doc(
			{
				"doctype": "CRM High School",
				"school_name": "_Update API School",
				"school_code": "_UPDATE_API_SCHOOL",
				"province": province,
				"ward": ward,
			}
		).insert(ignore_permissions=True)

		try:
			result = update_school(
				school.name, {"school_name": "_Updated API School", "address": "API address"}
			)
			self.assertEqual(result["name"], school.name)
			self.assertEqual(result["updated_fields"]["school_name"], "_Updated API School")
			self.assertEqual(frappe.db.get_value("CRM High School", school.name, "address"), "API address")

			frappe.set_user("Guest")
			with self.assertRaises(frappe.PermissionError):
				update_school(school.name, {"address": "Guest address"})
		finally:
			frappe.set_user("Administrator")
			frappe.delete_doc("CRM High School", school.name, force=True, ignore_permissions=True)
			frappe.set_user(previous_user)

	def test_update_student_saves_through_frappe(self):
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		student = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"student_name": "_Update API Student",
				"phone": "0981000077",
				"enrollment_status": "NEW",
			}
		).insert(ignore_permissions=True)

		try:
			result = update_student(
				student.name, {"student_name": "_Updated API Student", "email": "api@example.com"}
			)
			self.assertEqual(result["name"], student.name)
			self.assertEqual(
				frappe.db.get_value("CRM Lead", student.name, ["student_name", "email"], as_dict=True),
				{"student_name": "_Updated API Student", "email": "api@example.com"},
			)
		finally:
			frappe.delete_doc("CRM Lead", student.name, force=True, ignore_permissions=True)
			frappe.set_user(previous_user)
