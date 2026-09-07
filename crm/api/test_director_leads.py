from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import director_leads


class TestDirectorLeads(FrappeTestCase):
	def test_sales_profiles_can_read_leads(self):
		permissions = {permission.role: permission for permission in frappe.get_meta("CRM Lead").permissions}

		for role in ("CTV Sale", "Sale", "Lead Sale"):
			with self.subTest(role=role):
				self.assertTrue(permissions[role].read)

	def test_query_normalization_accepts_contract_values(self):
		query = director_leads._parse_query(
			admission_year="2026",
			page="2",
			page_size="10",
			query="  Nguyen  ",
			status="NEW",
			campaign=" Tuyen sinh mua thu 2026 ",
			order="asc",
		)

		self.assertEqual(
			query,
			{
				"admission_year": "2026",
				"page": 2,
				"page_size": 10,
				"query": "Nguyen",
				"status": "NEW",
				"campaign": "Tuyen sinh mua thu 2026",
				"order": "asc",
			},
		)

	def test_query_normalization_rejects_invalid_values(self):
		for kwargs in (
			{"page": "0"},
			{"page_size": "101"},
			{"admission_year": "2026.5"},
			{"order": "sideways"},
		):
			with self.subTest(kwargs=kwargs):
				with self.assertRaises(frappe.ValidationError):
					director_leads._parse_query(**kwargs)

	def test_lead_filters_search_expected_fields_and_status(self):
		query = director_leads._parse_query(
			admission_year="2026", query="Nguyen", status="NEW", campaign="Tuyen sinh mua thu 2026"
		)
		filters, or_filters = director_leads._lead_filters(query)

		self.assertEqual(
			filters,
			{
				"admission_year": "2026",
				"enrollment_status": "NEW",
				"campaign": "Tuyen sinh mua thu 2026",
			},
		)
		self.assertEqual(
			or_filters,
			[
				["name", "like", "%Nguyen%"],
				["lead_code", "like", "%Nguyen%"],
				["student_name", "like", "%Nguyen%"],
				["phone", "like", "%Nguyen%"],
				["email", "like", "%Nguyen%"],
				["high_school", "like", "%Nguyen%"],
				["owner_staff", "like", "%Nguyen%"],
				["source", "like", "%Nguyen%"],
			],
		)

	def test_lead_filters_resolve_campaign_stable_code(self):
		with (
			patch.object(director_leads.frappe.db, "exists", return_value=False),
			patch.object(
				director_leads.frappe.db,
				"get_value",
				return_value="Tuyen sinh mua thu 2026",
			),
		):
			filters, _ = director_leads._lead_filters(director_leads._parse_query(campaign="CAM-2026-00001"))

		self.assertEqual(filters["campaign"], "Tuyen sinh mua thu 2026")

	def test_lead_row_mapping_uses_lookup_labels_without_fabrication(self):
		row = frappe._dict(
			{
				"name": "LEAD-2026-00001",
				"lead_code": "LD-2026-00001",
				"processing_status": "ASSIGNED",
				"student_name": "Nguyễn Minh An",
				"phone": "0900000000",
				"high_school": "HS-1",
				"enrollment_status": "NEW",
				"owner_staff": "STAFF-1",
				"source": "SRC-1",
				"creation": "2026-09-07 10:00:00",
			}
		)
		self.assertIsNone(director_leads._parse_query(campaign="all")["campaign"])
		item = director_leads._map_lead_row(
			row,
			lookups={
				"schools": {"HS-1": "THPT Châu Văn Liêm"},
				"statuses": {"NEW": "Mới"},
				"owners": {"STAFF-1": "Trần Quốc Bảo"},
				"sources": {"SRC-1": "Website"},
			},
		)

		self.assertEqual(
			item,
			{
				"id": "LEAD-2026-00001",
				"leadCode": "LD-2026-00001",
				"studentId": "LEAD-2026-00001",
				"initials": "MA",
				"name": "Nguyễn Minh An",
				"phone": "0900000000",
				"school": "THPT Châu Văn Liêm",
				"status": "Mới",
				"statusCode": "NEW",
				"source": "Website",
				"owner": "Trần Quốc Bảo",
				"processingStatus": "ASSIGNED",
				"createdAt": "2026-09-07T10:00:00+07:00",
			},
		)

	def test_list_endpoint_returns_paginated_envelope(self):
		row = frappe._dict(name="LEAD-1", student_name="Nguyễn Minh An")
		with (
			patch.object(director_leads, "_require_access"),
			patch.object(director_leads, "_resolve_status", return_value="NEW"),
			patch.object(director_leads, "_count_leads", side_effect=[1, 8, 1, 1, 1]),
			patch.object(director_leads, "_fetch_lead_rows", return_value=[row]),
			patch.object(director_leads, "_load_lookups", return_value={"statuses": {"NEW": "Mới"}}),
			patch.object(
				director_leads,
				"_map_lead_row",
				return_value={"id": "LEAD-1", "status": "Mới"},
			),
			patch.object(director_leads, "_status_options", return_value=[{"value": "NEW", "label": "Mới"}]),
		):
			response = director_leads.get_director_leads(
				admissionYear="2026",
				page="2",
				pageSize="1",
				q=" Nguyen ",
				status="NEW",
				campaign="CAM-2026-00001",
			)

		self.assertEqual(response["data"], [{"id": "LEAD-1", "status": "Mới"}])
		self.assertEqual(response["meta"]["total"], 1)
		self.assertEqual(response["meta"]["totalAll"], 8)
		self.assertEqual(response["meta"]["page"], 2)
		self.assertEqual(response["meta"]["pageSize"], 1)
		self.assertEqual(response["meta"]["totalPages"], 1)
		self.assertFalse(response["meta"]["hasNextPage"])
		self.assertEqual(response["meta"]["status"], "NEW")
		self.assertEqual(
			response["meta"]["stats"],
			{"total": 1, "inProgress": 1, "closed": 1, "conversionRate": 100},
		)

	def test_detail_endpoint_checks_read_permission_before_projection(self):
		doc = frappe._dict(name="LEAD-1", student_name="Nguyễn Minh An")
		doc.has_permission = lambda permission_type: permission_type == "read"
		with (
			patch.object(director_leads, "_require_access"),
			patch.object(director_leads.frappe, "get_doc", return_value=doc),
			patch.object(director_leads.frappe.utils, "now_datetime", return_value="2026-09-07 10:00:00"),
			patch.object(director_leads, "_load_lookups", return_value={"statuses": {}}),
			patch.object(director_leads, "_event_projection", return_value=([], [])),
			patch.object(director_leads, "_lead_log", return_value=[]),
			patch.object(director_leads, "_map_detail_row", return_value={"id": "LEAD-1"}),
		):
			response = director_leads.get_director_lead(" LEAD-1 ")

		self.assertEqual(response["lead"], {"id": "LEAD-1"})
		self.assertEqual(response["log"], [])

	def test_detail_endpoint_hides_lead_without_permission(self):
		doc = frappe._dict(name="LEAD-1", student_name="Nguyễn Minh An")
		doc.has_permission = lambda permission_type: False
		with (
			patch.object(director_leads, "_require_access"),
			patch.object(director_leads.frappe, "get_doc", return_value=doc),
			self.assertRaises(frappe.DoesNotExistError),
		):
			director_leads.get_director_lead("LEAD-1")

	def test_event_projection_skips_unreadable_marketing_engagement(self):
		with (
			patch.object(director_leads, "_table_exists", return_value=True),
			patch.object(director_leads.frappe, "get_list", side_effect=frappe.PermissionError),
		):
			self.assertEqual(director_leads._event_projection("LEAD-1", {}), ([], []))
