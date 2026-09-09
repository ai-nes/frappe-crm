from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import lead_mapping
from crm.api.lead_mapping import (
	LeadMappingError,
	_normalize_public_lead_payload,
	_parse_csv_rows,
	_parse_public_payload,
	create_public_lead,
	get_public_high_schools,
	get_public_leads,
	get_public_majors,
	get_public_provinces,
	get_public_wards,
	split_multi_value,
)


class TestLeadMappingContract(TestCase):
	def test_split_multi_value_deduplicates_csv_values(self):
		self.assertEqual(
			split_multi_value("Segment A; Segment B\nSegment A"),
			["Segment A", "Segment B"],
		)

	def test_parse_csv_rows_accepts_mapping_headers(self):
		rows = _parse_csv_rows(
			"\ufeffHọ và Tên,Di động,Tỉnh/Thành Phố,Nguồn,Giao cho\n"
			"Nguyễn Văn An,0900000000,Hồ Chí Minh,Promoter,sales@example.com"
		)

		self.assertEqual(
			rows,
			[
				{
					"student_name": "Nguyễn Văn An",
					"phone": "0900000000",
					"province": "Hồ Chí Minh",
					"source": "Promoter",
					"assigned_to": "sales@example.com",
				}
			],
		)

	def test_parse_csv_rows_requires_all_non_nullable_headers(self):
		with self.assertRaises(LeadMappingError) as context:
			_parse_csv_rows("Họ và Tên,Di động,Tỉnh/Thành Phố,Nguồn\nAn,0900000000,Hà Nội,Promoter")

		self.assertEqual(context.exception.code, "CSV_MISSING_HEADERS")
		self.assertIn("assigned_to", str(context.exception))

	def test_public_payload_rejects_server_managed_fields(self):
		with self.assertRaises(LeadMappingError) as context:
			_parse_public_payload({"student_name": "An", "processing_status": "PROCESSED"})

		self.assertEqual(context.exception.code, "SERVER_MANAGED_FIELD")
		self.assertIn("processing_status", str(context.exception))

	def test_public_payload_requires_campaign_code_during_normalization(self):
		from crm.api.lead_mapping import _normalize_public_lead_payload

		with self.assertRaises(LeadMappingError) as context:
			_normalize_public_lead_payload({"student_name": "An"})

		self.assertEqual(context.exception.code, "REQUIRED_FIELD")
		self.assertIn("campaign_code", str(context.exception))

	def test_public_payload_normalizes_optional_intake_fields(self):
		with (
			patch("crm.api.lead_mapping._check_unique") as check_unique,
			patch("crm.api.lead_mapping._resolve_campaign_code", return_value="_Test Campaign"),
			patch("crm.api.lead_mapping.frappe.db.get_value", return_value=None),
		):
			values = _normalize_public_lead_payload(
				{
					"student_name": "An",
					"phone": "+84981000099",
					"id_number": "012-345 678 901",
					"campaign_code": "CAM-2026-00001",
					"segments": ["Scholarship", "Scholarship"],
					"assignment_priority": "HIGH",
				}
			)

		self.assertEqual(values["phone"], "0981000099")
		self.assertEqual(values["id_number"], "012345678901")
		self.assertEqual(frappe.parse_json(values["segments"]), ["Scholarship"])
		self.assertEqual(values["assignment_priority"], "high")
		self.assertEqual(values["campaign"], "_Test Campaign")
		check_unique.assert_not_called()

	def test_public_payload_keeps_repeat_submissions_for_one_student(self):
		with (
			patch("crm.api.lead_mapping._resolve_campaign_code", return_value="_Test Campaign"),
			patch("crm.api.lead_mapping.frappe.db.get_value", return_value=None),
		):
			first = _normalize_public_lead_payload(
				{
					"student_name": "An",
					"phone": "0981000099",
					"email": "an@example.com",
					"id_number": "012345678901",
					"campaign_code": "CAM-2026-00001",
				}
			)
			second = _normalize_public_lead_payload(
				{
					"student_name": "An",
					"phone": "0981000099",
					"email": "an@example.com",
					"id_number": "012345678901",
					"campaign_code": "CAM-2026-00001",
				}
			)

		self.assertEqual(first["id_number"], second["id_number"])
		self.assertEqual(first["phone"], second["phone"])
		self.assertEqual(first["email"], second["email"])

	def test_public_payload_rejects_removed_cccd_field(self):
		with self.assertRaises(LeadMappingError) as context:
			_parse_public_payload(
				{
					"student_name": "An",
					"campaign_code": "CAM-2026-00001",
					"cccd": "012345678901",
				}
			)

		self.assertEqual(context.exception.code, "UNKNOWN_FIELD")
		self.assertIn("cccd", str(context.exception))

	@patch("crm.api.lead_mapping._create_public_lead", return_value={"ok": True})
	def test_public_endpoint_ignores_frappe_cmd_metadata(self, create_lead):
		result = create_public_lead(student_name="An", cmd="crm.api.lead_mapping.create_public_lead")

		self.assertEqual(result, {"ok": True})
		create_lead.assert_called_once_with({"student_name": "An"})

	@patch(
		"crm.api.lead_mapping.frappe.get_all",
		return_value=[{"name": "Ho Chi Minh City", "province_name": "Hồ Chí Minh", "province_code": "HCM"}],
	)
	def test_public_provinces_return_dropdown_items(self, get_all):
		result = get_public_provinces()

		self.assertEqual(
			result,
			{
				"items": [{"value": "Ho Chi Minh City", "label": "Hồ Chí Minh", "code": "HCM"}],
				"total": 1,
			},
		)
		get_all.assert_called_once()

	@patch("crm.api.lead_mapping.resolve_province", return_value="Ho Chi Minh City")
	@patch("crm.api.lead_mapping.frappe.db.exists", return_value=True)
	@patch(
		"crm.api.lead_mapping.frappe.get_all",
		return_value=[
			{
				"name": "Ward 1 - Ho Chi Minh City",
				"ward_name": "Phường Bến Nghé",
				"ward_code": "HCM-001",
				"ward_type": "Ward",
				"province": "Ho Chi Minh City",
			}
		],
	)
	def test_public_wards_require_and_scope_province(self, get_all, exists, resolve_province):
		result = get_public_wards("HCM")

		self.assertEqual(result["total"], 1)
		self.assertEqual(result["items"][0]["value"], "Ward 1 - Ho Chi Minh City")
		self.assertEqual(result["items"][0]["ward_type"], "Ward")
		resolve_province.assert_called_once_with("HCM")
		exists.assert_called_once_with("CRM Province", "Ho Chi Minh City")
		self.assertEqual(get_all.call_args.kwargs["filters"], {"province": "Ho Chi Minh City"})

	@patch("crm.api.lead_mapping.resolve_ward", return_value="Ward 1 - Ho Chi Minh City")
	@patch("crm.api.lead_mapping.frappe.db.exists", return_value=True)
	@patch(
		"crm.api.lead_mapping.frappe.get_all",
		return_value=[
			{
				"name": "High School 1",
				"school_name": "THPT Nguyễn Huệ",
				"school_code": "HCM-THPT-001",
				"school_type": "Public",
				"province": "Ho Chi Minh City",
				"ward": "Ward 1 - Ho Chi Minh City",
			}
		],
	)
	def test_public_high_schools_scope_ward_and_only_active(self, get_all, exists, resolve_ward):
		result = get_public_high_schools("HCM-001")

		self.assertEqual(result["items"][0]["label"], "THPT Nguyễn Huệ")
		resolve_ward.assert_called_once_with("HCM-001")
		exists.assert_called_once_with("CRM Ward", "Ward 1 - Ho Chi Minh City")
		self.assertEqual(
			get_all.call_args.kwargs["filters"],
			{"ward": "Ward 1 - Ho Chi Minh City", "is_active": 1},
		)

	@patch(
		"crm.api.lead_mapping.frappe.get_all",
		return_value=[
			{
				"name": "Software Engineering",
				"major_name": "Kỹ thuật phần mềm",
				"major_code": "SE",
				"degree_name": "Cử nhân",
				"major_group": "Technology",
			}
		],
	)
	def test_public_majors_return_active_dropdown_items(self, get_all):
		result = get_public_majors()

		self.assertEqual(result["items"][0]["code"], "SE")
		self.assertEqual(get_all.call_args.kwargs["filters"], {"is_active": 1})

	def test_public_leads_filter_campaign_dates_and_paginate(self):
		rows = [
			{
				"name": "LEAD-1",
				"lead_code": "HS-2026-HCM-000001",
				"student_name": "An",
				"phone": "0900000001",
				"email": "an@example.com",
				"major": "Software Engineering",
				"high_school": "SCHOOL-1",
				"province": "PROVINCE-1",
				"ward": "WARD-1",
				"processing_status": "NEW",
				"resolution": "PENDING",
				"campaign": "Campaign 1",
				"creation": "2026-09-15 12:30:00",
			}
		]
		province_rows = [{"name": "PROVINCE-1", "province_name": "Khánh Hòa"}]
		ward_rows = [{"name": "WARD-1", "ward_name": "Khánh Hòa"}]
		school_rows = [{"name": "SCHOOL-1", "school_name": "THPT Nguyễn Văn An"}]
		with (
			patch.object(lead_mapping, "_resolve_campaign_code", return_value="Campaign 1"),
			patch.object(
				lead_mapping.frappe,
				"get_all",
				side_effect=[rows, province_rows, ward_rows, school_rows],
			) as get_all,
			patch.object(lead_mapping.frappe.db, "count", return_value=3) as count,
		):
			result = get_public_leads(
				campaign_code="CAM-2026-00001",
				startdate="2026-09-01",
				enddate="2026-09-30",
				start="10",
				page_length="25",
			)

		expected_leads = [
			{
				**rows[0],
				"high_school": "THPT Nguyễn Văn An",
				"province": "Khánh Hòa",
				"ward": "Khánh Hòa",
			}
		]
		self.assertEqual(result, {"total": 3, "start": 10, "page_length": 25, "leads": expected_leads})
		filters = [
			["campaign", "=", "Campaign 1"],
			["creation", ">=", "2026-09-01 00:00:00"],
			["creation", "<", "2026-10-01 00:00:00"],
		]
		lead_query = get_all.call_args_list[0]
		self.assertEqual(lead_query.kwargs["filters"], filters)
		self.assertEqual(lead_query.kwargs["fields"], list(lead_mapping.PUBLIC_LEAD_LIST_FIELDS))
		self.assertEqual(lead_query.kwargs["limit_start"], 10)
		self.assertEqual(lead_query.kwargs["limit_page_length"], 25)
		count.assert_called_once_with("CRM Lead", filters=filters)

	def test_public_leads_accept_snake_case_date_aliases(self):
		with (
			patch.object(lead_mapping, "_resolve_campaign_code", return_value="Campaign 1"),
			patch.object(lead_mapping.frappe, "get_all", return_value=[]),
			patch.object(lead_mapping.frappe.db, "count", return_value=0),
		):
			result = get_public_leads(
				campaign_code="CAM-2026-00001",
				start_date="2026-09-01",
				end_date="2026-09-30",
			)

		self.assertEqual(result["total"], 0)

	def test_public_leads_reject_invalid_date_range_and_pagination(self):
		with patch.object(lead_mapping, "_resolve_campaign_code", return_value="Campaign 1"):
			with self.assertRaises(LeadMappingError) as context:
				get_public_leads(
					campaign_code="CAM-2026-00001",
					startdate="2026-10-01",
					enddate="2026-09-01",
				)
			self.assertEqual(context.exception.code, "INVALID_DATE")

			with self.assertRaises(LeadMappingError) as context:
				get_public_leads(campaign_code="CAM-2026-00001", page_length=101)
			self.assertEqual(context.exception.code, "INVALID_PAGINATION")

	def test_public_lead_list_is_guest_whitelisted(self):
		source = lead_mapping.__loader__.get_source(lead_mapping.__name__)
		self.assertIn('@frappe.whitelist(allow_guest=True, methods=["GET"])', source)

	def test_internal_batch_payload_allows_missing_campaign_code(self):
		with (
			patch("crm.api.lead_mapping._check_unique"),
			patch("crm.api.lead_mapping._resolve_source", return_value="Promoter"),
			patch("crm.api.lead_mapping._resolve_province", return_value="Hồ Chí Minh"),
			patch("crm.api.lead_mapping.frappe.db.exists", return_value=True),
			patch("crm.api.lead_mapping.frappe.db.get_value", return_value=None),
		):
			values = _normalize_public_lead_payload(
				{
					"student_name": "An",
					"phone": "0981000010",
					"province": "Hồ Chí Minh",
					"source": "Promoter",
				},
				require_campaign=False,
			)

		self.assertIsNone(values["campaign"])


class TestLeadMappingIntegration(FrappeTestCase):
	def test_create_lead_resolves_csv_labels_and_enforces_contract(self):
		from crm.api.lead_mapping import _create_lead

		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		created_name = None
		try:
			result = _create_lead(
				{
					"student_name": "_Lead Mapping API Student",
					"phone": "0981000098",
					"province": "Hồ Chí Minh",
					"source": "Promoter",
					"assigned_to": "ctvsale@gmail.com",
					"advertising_channel": "Facebook",
				}
			)
			created_name = result["name"]
			self.assertEqual(result["doctype"], "CRM Lead")
			self.assertRegex(result["leadCode"], r"^HS-\d{4}-[A-Z]+-\d{6}$")
			self.assertEqual(result["lead_code"], result["leadCode"])
			self.assertIn(
				frappe.db.get_value("CRM Lead", created_name, "province"),
				{"Hồ Chí Minh", "Ho Chi Minh City"},
			)
			self.assertIn(
				frappe.db.get_value("CRM Lead", created_name, "assigned_to"),
				{"CTV Sale", "Cộng tác viên Sale"},
			)
			self.assertEqual(frappe.db.get_value("CRM Lead", created_name, "source"), "Promoter")
			self.assertEqual(
				frappe.db.get_value("CRM Lead", created_name, "advertising_channel"),
				"Facebook",
			)
		finally:
			if created_name and frappe.db.exists("CRM Lead", created_name):
				frappe.delete_doc("CRM Lead", created_name, force=True, ignore_permissions=True)
			frappe.set_user(previous_user)

	def test_import_leads_rolls_back_only_invalid_rows(self):
		from crm.api.lead_mapping import import_leads

		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		created_names = []
		try:
			result = import_leads(
				csv_content=(
					"Họ và Tên,Di động,Tỉnh/Thành Phố,Nguồn,Giao cho\n"
					"_Lead Mapping Import Student,0981000097,Hồ Chí Minh,Promoter,ctvsale@gmail.com\n"
					"_Lead Mapping Import Invalid,not-a-phone,Hồ Chí Minh,Promoter,ctvsale@gmail.com"
				)
			)
			created_names = [student["name"] for student in result["students"]]
			self.assertEqual(result["total"], 2)
			self.assertEqual(result["created"], 1)
			self.assertEqual(result["failed"], 1)
			self.assertEqual(result["errors"][0]["code"], "INVALID_PHONE")
		finally:
			for name in created_names:
				if frappe.db.exists("CRM Lead", name):
					frappe.delete_doc("CRM Lead", name, force=True, ignore_permissions=True)
			frappe.set_user(previous_user)
