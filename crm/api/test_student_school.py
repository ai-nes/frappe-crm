import json
from unittest import TestCase
from unittest.mock import Mock, call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.student_school import (
	create_school,
	create_student,
	create_student_with_lead,
	delete_school,
	delete_student,
	get_field_options,
	get_school,
	get_schools,
	get_student,
	get_student_high_school_score,
	update_school,
	update_student,
	update_student_high_school_score,
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
	def _linked_create_mocks(self, *, student_insert_error=None):
		lead = Mock()
		lead.doctype = "CRM Lead"
		lead.name = "HS-2026-HCM-000001"
		lead.get.side_effect = lambda fieldname: {
			"lead_code": "HS-2026-HCM-000001",
			"processing_status": "NEW",
			"resolution": "PENDING",
		}.get(fieldname)
		student = Mock()
		student.doctype = "CRM Student"
		student.name = "HS-2026-HCM-000001"
		student.get.side_effect = lambda fieldname: {
			"full_name": "Nguyen Van B",
			"phone": "0900000001",
			"student_stage": "New",
			"source_lead": "HS-2026-HCM-000001",
		}.get(fieldname)
		if student_insert_error:
			student.insert.side_effect = student_insert_error

		lead_meta = Mock()
		lead_meta.get_field.return_value.options = (
			"New\nWorking\nContacted\nQualified\nUnqualified\nConverted\nLost"
		)
		student_meta = Mock(
			fields=[
				Mock(fieldname="full_name"),
				Mock(fieldname="phone"),
				Mock(fieldname="student_stage"),
				Mock(fieldname="source_lead"),
			]
		)
		return lead, student, lead_meta, student_meta

	@patch("crm.api.student_school._normalize_lead_payload")
	def test_create_student_with_lead_creates_and_links_real_student(self, normalize):
		lead, student, _lead_meta, student_meta = self._linked_create_mocks()
		normalize.return_value = (
			{
				"student_name": "Nguyen Van B",
				"phone": "0900000001",
				"student_stage": "New",
			},
			["TAG-ONE", "TAG-TWO"],
			[],
			"sales@example.com",
		)
		with (
			patch.object(frappe, "get_meta", return_value=student_meta),
			patch.object(frappe, "get_doc", side_effect=[lead, student]) as get_doc,
			patch.object(frappe, "generate_hash", return_value="abc12345"),
			patch.object(frappe.utils, "now_datetime", return_value="2026-09-09 10:00:00"),
			patch.object(frappe.db, "savepoint"),
		):
			result = create_student_with_lead(
				{
					"student_name": "Nguyen Van B",
					"phone": "0900000001",
					"province": "PROVINCE-001",
					"source": "Promoter",
					"assigned_to": "sales@example.com",
					"tags": ["TAG-ONE", "TAG-TWO"],
				}
			)

		self.assertEqual(result["doctype"], "CRM Student")
		self.assertEqual(result["name"], student.name)
		self.assertEqual(result["student"]["student_stage"], "New")
		self.assertEqual(result["lead"]["student"], student.name)
		student_values = get_doc.call_args_list[1].args[0]
		self.assertEqual(student_values["student_stage"], "New")
		self.assertEqual(
			student_values["tags"],
			[{"tag": "TAG-ONE"}, {"tag": "TAG-TWO"}],
		)
		self.assertIsNotNone(student_values["converted_at"])
		lead.set.assert_has_calls(
			[
				call("student", student.name),
				call("converted_student", student.name),
				call("converted_at", student_values["converted_at"]),
				call("processing_status", "CLOSED"),
				call("resolution", "CREATED"),
				call("resolution_reason", "CREATED handoff completed."),
			]
		)
		lead.save.assert_called_once_with(ignore_permissions=True, ignore_version=False)
		self.assertEqual(lead.check_permission.call_args.args, ("create",))
		self.assertEqual(student.check_permission.call_args.args, ("create",))

	@patch("crm.api.student_school._normalize_lead_payload")
	def test_create_student_with_lead_rolls_back_when_student_insert_fails(self, normalize):
		lead, student, _lead_meta, student_meta = self._linked_create_mocks(
			student_insert_error=RuntimeError("student insert failed")
		)
		normalize.return_value = (
			{
				"student_name": "Nguyen Van B",
				"phone": "0900000001",
				"processing_status": "NEW",
			},
			[],
			[],
			"sales@example.com",
		)
		with (
			patch.object(frappe, "get_meta", return_value=student_meta),
			patch.object(frappe, "get_doc", side_effect=[lead, student]),
			patch.object(frappe, "generate_hash", return_value="abc12345"),
			patch.object(frappe.utils, "now_datetime", return_value="2026-09-09 10:00:00"),
			patch.object(frappe.db, "savepoint"),
			patch.object(frappe.db, "rollback") as rollback,
		):
			with self.assertRaisesRegex(RuntimeError, "student insert failed"):
				create_student_with_lead(
					{
						"student_name": "Nguyen Van B",
						"phone": "0900000001",
						"province": "PROVINCE-001",
						"source": "Promoter",
						"assigned_to": "sales@example.com",
					}
				)

		rollback.assert_called_once()

	def test_create_student_returns_created_fields(self):
		doc = _FakeDocument("CRM Student", "STU-NEW-001")
		with patch.object(frappe, "new_doc", return_value=doc):
			result = create_student({"student_name": "Nguyen Van B", "phone": "0900000001"})

		self.assertEqual(
			result,
			{
				"doctype": "CRM Student",
				"name": "STU-NEW-001",
				"created_fields": {
					"full_name": "Nguyen Van B",
					"phone": "0900000001",
					"student_name": "Nguyen Van B",
				},
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
		doc = _FakeDocument("CRM Student", "STU-GET-001")
		doc.values = {"full_name": "Nguyen Van C", "phone": "0900000002", "email": "c@example.com"}
		meta = Mock(
			fields=[
				Mock(fieldname="full_name", in_list_view=1),
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
				"doctype": "CRM Student",
				"name": "STU-GET-001",
				"fields": {
					"full_name": "Nguyen Van C",
					"phone": "0900000002",
					"student_name": "Nguyen Van C",
				},
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

	def test_get_student_high_school_score_combines_student_and_admission_profile(self):
		student = _FakeDocument("CRM Student", "STU-SCORE-001")
		student.values = {
			"admission_year": "2026",
			"transcript_score": 8.25,
			"total_score": 27.5,
		}
		profile = _FakeDocument("CRM Student Admission Profile", "SAP-SCORE-001")
		profile.values = {
			"admission_year": "2026",
			"grade_12_gpa": 8.8,
			"exam_candidate_number": "012345",
			"score_details": '{"toan": 9}',
			"encouragement_type": "HSG",
			"encouragement_score": 1.0,
			"priority_type": "KV1",
			"priority_score": 0.25,
		}
		with (
			patch.object(frappe, "get_doc", side_effect=[student, profile]),
			patch.object(frappe, "get_list", return_value=[{"name": profile.name}]),
		):
			result = get_student_high_school_score(student.name)

		self.assertEqual(result["admission_profile"], profile.name)
		self.assertEqual(result["admission_year"], "2026")
		self.assertEqual(
			result["fields"],
			{
				"graduation_score": None,
				"transcript_score": 8.25,
				"total_score": 27.5,
				"is_high_school_graduate": False,
				"graduation_year": None,
				"academic_rank": None,
				"priority_group": None,
				"graduation_classification": None,
				"conduct_rank": None,
				"grade_12_gpa": 8.8,
				"exam_candidate_number": "012345",
				"score_details": {"toan": 9},
				"encouragement_type": "HSG",
				"encouragement_score": 1.0,
				"priority_type": "KV1",
				"priority_score": 0.25,
			},
		)
		self.assertEqual(student.check_permission_calls, ["read"])
		self.assertEqual(profile.check_permission_calls, ["read"])

	def test_update_student_high_school_score_saves_owned_fields(self):
		student = _FakeDocument("CRM Student", "STU-SCORE-001")
		student.values = {
			"admission_year": "2026",
			"academic_results": [{"school_year": "2025-2026", "grade": "12", "academic_rank": "Khá"}],
		}
		profile = _FakeDocument("CRM Student Admission Profile", "SAP-SCORE-001")
		profile.values = {"admission_year": "2026"}
		with (
			patch.object(frappe, "get_doc", side_effect=[student, profile]),
			patch.object(frappe, "get_list", return_value=[{"name": profile.name}]),
		):
			result = update_student_high_school_score(
				student.name,
				{
					"graduation_score": 8.6,
					"is_high_school_graduate": True,
					"graduation_year": 2026,
					"academic_rank": "Giỏi",
					"priority_group": "KV1",
					"graduation_classification": "Khá",
					"conduct_rank": "Tốt",
					"transcript_score": 8.4,
					"total_score": 28,
					"grade_12_gpa": 8.9,
					"score_details": {"toan": 9.5},
				},
			)

		self.assertEqual(result["updated_fields"]["grade_12_gpa"], 8.9)
		self.assertEqual(result["fields"]["score_details"], {"toan": 9.5})
		self.assertEqual(student.values["graduation_score"], 8.6)
		self.assertEqual(student.values["transcript_score"], 8.4)
		self.assertEqual(student.values["total_score"], 28)
		self.assertEqual(student.values["academic_results"][0]["academic_rank"], "Giỏi")
		self.assertEqual(json.loads(profile.values["score_details"]), {"toan": 9.5})
		self.assertTrue(profile.values["is_high_school_graduate"])
		self.assertEqual(profile.values["graduation_year"], 2026)
		self.assertEqual(profile.values["priority_group"], "KV1")
		self.assertEqual(profile.values["graduation_classification"], "Khá")
		self.assertEqual(profile.values["conduct_rank"], "Tốt")
		self.assertEqual(student.check_permission_calls, ["write"])
		self.assertEqual(profile.check_permission_calls, ["write"])
		self.assertEqual(student.save_calls, 1)
		self.assertEqual(profile.save_calls, 1)

	def test_update_student_high_school_score_rejects_negative_values_before_loading(self):
		with patch.object(frappe, "get_doc") as get_doc:
			with self.assertRaises(frappe.ValidationError):
				update_student_high_school_score("STU-SCORE-001", {"total_score": -1})

		get_doc.assert_not_called()

	def test_update_student_high_school_score_rejects_graduation_score_above_30(self):
		with patch.object(frappe, "get_doc") as get_doc:
			with self.assertRaises(frappe.ValidationError):
				update_student_high_school_score("STU-SCORE-001", {"graduation_score": 30.01})

		get_doc.assert_not_called()

	def test_update_student_high_school_score_requires_profile_for_profile_fields(self):
		student = _FakeDocument("CRM Student", "STU-SCORE-001")
		with (
			patch.object(frappe, "get_doc", return_value=student),
			patch.object(frappe, "get_list", return_value=[]),
		):
			with self.assertRaises(frappe.DoesNotExistError):
				update_student_high_school_score(
					student.name,
					{"grade_12_gpa": 8.5},
				)

		self.assertEqual(student.check_permission_calls, ["write"])
		self.assertEqual(student.save_calls, 0)

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

	def test_get_field_options_filters_school_area_by_selected_high_school(self):
		field = Mock(fieldname="school_area", fieldtype="Link", options="CRM School Area")
		source_meta = Mock(fields=[field])
		target_meta = Mock(
			fields=[Mock(fieldname="code"), Mock(fieldname="display_name")],
			title_field="display_name",
		)
		with (
			patch.object(frappe, "get_meta", side_effect=[source_meta, target_meta]),
			patch.object(
				frappe,
				"get_list",
				side_effect=[
					[{"school_area": "KV3"}],
					[{"name": "KV3", "display_name": "Khu vực 3"}],
				],
			) as get_list,
		):
			result = get_field_options(
				"CRM High School",
				"school_area",
				high_school="SCHOOL-001",
				limit=1,
			)

		self.assertEqual(result["target_doctype"], "CRM School Area")
		self.assertEqual(result["options"], [{"value": "KV3", "label": "Khu vực 3"}])
		self.assertEqual(
			get_list.call_args_list[0].kwargs,
			{
				"filters": {"name": "SCHOOL-001"},
				"fields": ["school_area"],
				"limit_page_length": 1,
			},
		)
		self.assertEqual(get_list.call_args_list[1].kwargs["filters"], {"code": "KV3"})

	def test_get_field_options_rejects_unknown_doctype_and_non_option_field(self):
		with self.assertRaises(frappe.ValidationError):
			get_field_options("CRM Province", "name")

		meta = Mock(fields=[Mock(fieldname="school_name", fieldtype="Data")])
		with patch.object(frappe, "get_meta", return_value=meta):
			with self.assertRaises(frappe.ValidationError):
				get_field_options("CRM High School", "school_name")

	def test_update_student_accepts_json_and_returns_updated_fields(self):
		doc = _FakeDocument("CRM Student", "STU-001")
		with patch.object(frappe, "get_doc", return_value=doc):
			result = update_student(
				"STU-001",
				json.dumps({"student_name": "Nguyen Van A", "phone": "0900000000"}),
			)

		self.assertEqual(
			result,
			{
				"doctype": "CRM Student",
				"name": "STU-001",
				"updated_fields": {
					"full_name": "Nguyen Van A",
					"phone": "0900000000",
					"student_name": "Nguyen Van A",
				},
			},
		)
		self.assertEqual(doc.values, {"full_name": "Nguyen Van A", "phone": "0900000000"})
		self.assertEqual(doc.check_permission_calls, ["write"])
		self.assertEqual(doc.save_calls, 1)

	def test_update_student_accepts_admission_method_for_later_workflow(self):
		doc = _FakeDocument("CRM Student", "STU-001")
		with patch.object(frappe, "get_doc", return_value=doc):
			result = update_student("STU-001", {"admission_method": "TRANSCRIPT_REVIEW"})

		self.assertEqual(result["updated_fields"], {"admission_method": "TRANSCRIPT_REVIEW"})
		self.assertEqual(doc.values, {"admission_method": "TRANSCRIPT_REVIEW"})

	def test_update_student_accepts_contact_person_fields(self):
		doc = _FakeDocument("CRM Student", "STU-001")
		fields = {
			"parent_other_phone": "0900000001",
			"parent_email": "parent@example.com",
			"father_name": "Nguyen Van An",
			"father_phone": "0900000002",
			"father_email": "father@example.com",
			"father_occupation": "Business",
			"mother_name": "Nguyen Thi An",
			"mother_phone": "0900000003",
			"mother_email": "mother@example.com",
			"mother_occupation": "Teacher",
		}
		with patch.object(frappe, "get_doc", return_value=doc):
			result = update_student("STU-001", fields)

		self.assertEqual(result["updated_fields"], fields)
		self.assertEqual(doc.values, fields)

	def test_update_student_updates_the_separate_contact_payment_account(self):
		student = _FakeDocument("CRM Student", "STU-001")
		account = _FakeDocument("CRM Student Payment Account", "PBA-001")
		fields = {
			"bank_name": "Vietcombank",
			"account_number": "123456789",
			"account_holder": "Nguyen Thi An",
		}
		with (
			patch.object(frappe, "get_doc", side_effect=[student, account]),
			patch.object(frappe, "get_all", return_value=[{"name": "PBA-001"}]),
		):
			result = update_student("STU-001", fields)

		self.assertEqual(result["updated_fields"], fields)
		self.assertEqual(
			account.values,
			{
				"bank_name": "Vietcombank",
				"account_number": "123456789",
				"account_holder_name": "Nguyen Thi An",
			},
		)
		self.assertEqual(account.check_permission_calls, ["write"])
		self.assertEqual(account.save_calls, 1)

	def test_ctv_sale_can_only_update_note_and_status_fields(self):
		with (
			patch.object(frappe, "session", Mock(user="ctv@example.com")),
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
		doc = _FakeDocument("CRM Student", "STU-DELETE-001")
		with (
			patch.object(frappe, "get_doc", return_value=doc),
			patch.object(frappe, "delete_doc") as delete_doc,
		):
			result = delete_student(" STU-DELETE-001 ")

		self.assertEqual(
			result,
			{"doctype": "CRM Student", "name": "STU-DELETE-001", "deleted": True},
		)
		self.assertEqual(doc.check_permission_calls, ["delete"])
		delete_doc.assert_called_once_with("CRM Student", "STU-DELETE-001")

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
				"doctype": "CRM Student",
				"full_name": "_Update API Student",
				"phone": "0981000077",
				"student_stage": "New",
			}
		).insert(ignore_permissions=True)

		try:
			result = update_student(
				student.name, {"student_name": "_Updated API Student", "email": "api@example.com"}
			)
			self.assertEqual(result["name"], student.name)
			self.assertEqual(
				frappe.db.get_value("CRM Student", student.name, ["full_name", "email"], as_dict=True),
				{"full_name": "_Updated API Student", "email": "api@example.com"},
			)
		finally:
			frappe.delete_doc("CRM Student", student.name, force=True, ignore_permissions=True)
			frappe.set_user(previous_user)
