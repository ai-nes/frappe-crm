from unittest import TestCase

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.lead_mapping import LeadMappingError, _parse_csv_rows, split_multi_value


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
