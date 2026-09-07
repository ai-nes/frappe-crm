from unittest import TestCase
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.lead_mapping import (
	LeadMappingError,
	_normalize_public_lead_payload,
	_parse_csv_rows,
	_parse_public_payload,
	create_public_lead,
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
			_parse_public_payload({"student_name": "An", "lead_status": "Qualified"})

		self.assertEqual(context.exception.code, "SERVER_MANAGED_FIELD")
		self.assertIn("lead_status", str(context.exception))

	def test_public_payload_requires_campaign_code_during_normalization(self):
		from crm.api.lead_mapping import _normalize_public_lead_payload

		with self.assertRaises(LeadMappingError) as context:
			_normalize_public_lead_payload({"student_name": "An"})

		self.assertEqual(context.exception.code, "REQUIRED_FIELD")
		self.assertIn("campaign_code", str(context.exception))

	def test_public_payload_normalizes_optional_intake_fields(self):
		with (
			patch("crm.api.lead_mapping._check_unique"),
			patch("crm.api.lead_mapping._resolve_campaign_code", return_value="_Test Campaign"),
			patch("crm.api.lead_mapping.frappe.db.get_value", return_value=None),
		):
			values = _normalize_public_lead_payload(
				{
					"student_name": "An",
					"phone": "+84981000099",
					"campaign_code": "CAM-2026-00001",
					"segments": ["Scholarship", "Scholarship"],
					"assignment_priority": "HIGH",
				}
			)

		self.assertEqual(values["phone"], "0981000099")
		self.assertEqual(frappe.parse_json(values["segments"]), ["Scholarship"])
		self.assertEqual(values["assignment_priority"], "high")
		self.assertEqual(values["campaign"], "_Test Campaign")

	def test_public_payload_maps_cccd_alias_to_id_number(self):
		payload = {
			"student_name": "An",
			"campaign_code": "CAM-2026-00001",
			"cccd": "012345678901",
		}
		self.assertEqual(_parse_public_payload(payload), payload)

		with (
			patch("crm.api.lead_mapping._resolve_campaign_code", return_value="_Test Campaign"),
			patch("crm.api.lead_mapping.frappe.db.get_value", return_value=None),
		):
			values = _normalize_public_lead_payload(payload)

		self.assertEqual(values["id_number"], "012345678901")

	def test_public_payload_rejects_conflicting_cccd_alias(self):
		with patch("crm.api.lead_mapping._resolve_campaign_code", return_value="_Test Campaign"):
			with self.assertRaises(LeadMappingError) as context:
				_normalize_public_lead_payload(
					{
						"student_name": "An",
						"campaign_code": "CAM-2026-00001",
						"cccd": "012345678901",
						"id_number": "012345678902",
					}
				)

		self.assertEqual(context.exception.code, "INVALID_INPUT")

	@patch("crm.api.lead_mapping._create_public_lead", return_value={"ok": True})
	def test_public_endpoint_ignores_frappe_cmd_metadata(self, create_lead):
		result = create_public_lead(student_name="An", cmd="crm.api.lead_mapping.create_public_lead")

		self.assertEqual(result, {"ok": True})
		create_lead.assert_called_once_with({"student_name": "An"})


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
			self.assertRegex(result["leadCode"], r"^LD-\d{4}-\d{5,}$")
			self.assertEqual(result["lead_code"], result["leadCode"])
			self.assertEqual(
				frappe.db.get_value("CRM Lead", created_name, "province"),
				"Ho Chi Minh City",
			)
			self.assertEqual(
				frappe.db.get_value("CRM Lead", created_name, "assigned_to"),
				"CTV Sale",
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
