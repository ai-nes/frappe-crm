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
			resolution="MATCHED",
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
				"resolution": "MATCHED",
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

		for resolver, value in (
			(director_leads._resolve_status, "PROSPECT"),
			(director_leads._resolve_resolution, "DONE"),
		):
			with self.subTest(resolver=resolver.__name__):
				with self.assertRaises(frappe.ValidationError):
					resolver(value)

	def test_lead_filters_search_expected_fields_and_status(self):
		query = director_leads._parse_query(
			admission_year="2026",
			query="Nguyen",
			status="NEW",
			resolution="MATCHED",
			campaign="Tuyen sinh mua thu 2026",
		)
		filters, or_filters = director_leads._lead_filters(query)

		self.assertEqual(
			filters,
			{
				"admission_year": "2026",
				"processing_status": "NEW",
				"resolution": "MATCHED",
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
				"resolution": "MATCHED",
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
				"status": "Đã phân công",
				"statusCode": "ASSIGNED",
				"result": "MATCHED",
				"source": "Website",
				"owner": "Trần Quốc Bảo",
				"contactNoAnswer": 0,
				"contactSuccess": 0,
				"processingStatus": "ASSIGNED",
				"createdAt": "2026-09-07T10:00:00+07:00",
			},
		)

	def test_processing_status_mapping_matches_form_submission_enum(self):
		for status, label in {
			"NEW": "Mới",
			"PROCESSING": "Đang xử lý",
			"PROCESSED": "Đã xử lý",
			"ASSIGNED": "Đã phân công",
			"CLOSED": "Đã đóng",
		}.items():
			with self.subTest(status=status):
				item = director_leads._map_lead_row(
					frappe._dict(name="LEAD-1", processing_status=status),
				)
				self.assertEqual(item["status"], label)
				self.assertEqual(item["statusCode"], status)

	def test_detail_mapping_includes_ward_label(self):
		detail = director_leads._map_detail_row(
			frappe._dict(name="LEAD-1", ward="WARD-1"),
			lookups={"wards": {"WARD-1": "Phường An Cư"}},
			event_titles=[],
		)

		self.assertEqual(detail["ward"], "Phường An Cư")

	def test_contact_counts_merge_call_logs_and_interactions_without_duplicates(self):
		rows = [
			frappe._dict(name="LEAD-1"),
			frappe._dict(name="LEAD-2", student="STUDENT-2"),
		]
		call_logs = [
			frappe._dict(
				name="CALL-1",
				reference_docname="LEAD-1",
				status="Completed",
				duration=60,
			),
			frappe._dict(
				name="CALL-2",
				reference_docname="LEAD-1",
				status="No Answer",
				duration=0,
			),
			frappe._dict(
				name="CALL-3",
				reference_docname="LEAD-2",
				status="Failed",
				duration=0,
			),
		]
		interactions = [
			frappe._dict(
				name="IX-DUPLICATE",
				student="LEAD-1",
				interaction_type="PHONE_CALL",
				channel="Call",
				outcome="Connected",
				reference_doctype="Call Log",
				reference_docname="CALL-1",
			),
			frappe._dict(
				name="IX-NO-ANSWER",
				student="LEAD-1",
				interaction_type="PHONE_CALL",
				channel="Call",
				outcome="No Response",
				reference_doctype=None,
				reference_docname=None,
			),
			frappe._dict(
				name="IX-CONNECTED",
				student="STUDENT-2",
				interaction_type="PHONE_CALL",
				channel="Call",
				outcome="Connected",
				reference_doctype=None,
				reference_docname=None,
			),
		]
		with (
			patch.object(director_leads, "_table_exists", return_value=True),
			patch.object(director_leads.frappe, "get_list", side_effect=[call_logs, interactions]),
		):
			counts = director_leads._contact_counts(rows)

		self.assertEqual(counts["LEAD-1"], {"no_answer": 2, "success": 1})
		self.assertEqual(counts["LEAD-2"], {"no_answer": 1, "success": 1})

	def test_list_endpoint_returns_paginated_envelope(self):
		row = frappe._dict(name="LEAD-1", student_name="Nguyễn Minh An")
		with (
			patch.object(director_leads, "_require_access"),
			patch.object(director_leads, "_list_scope_lead_ids", return_value=["LEAD-1"]),
			patch.object(director_leads, "_resolve_status", return_value="NEW"),
			patch.object(director_leads, "_resolve_resolution", return_value="MATCHED"),
			# total, totalAll, pendingNew, readyToAssign, then the campaign funnel.
			patch.object(director_leads, "_count_leads", side_effect=[1, 8, 3, 2, 1, 1, 1]),
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
				resolution="MATCHED",
				campaign="CAM-2026-00001",
			)

		self.assertEqual(response["data"], [{"id": "LEAD-1", "status": "Mới"}])
		self.assertEqual(response["meta"]["total"], 1)
		self.assertEqual(response["meta"]["totalAll"], 8)
		self.assertEqual(response["meta"]["pendingNew"], 3)
		self.assertEqual(response["meta"]["readyToAssign"], 2)
		self.assertEqual(response["meta"]["page"], 2)
		self.assertEqual(response["meta"]["pageSize"], 1)
		self.assertEqual(response["meta"]["totalPages"], 1)
		self.assertFalse(response["meta"]["hasNextPage"])
		self.assertEqual(response["meta"]["status"], "NEW")
		self.assertEqual(response["meta"]["resolution"], "MATCHED")
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
			patch.object(director_leads, "can_read_full_lead_board", return_value=False),
			patch.object(director_leads.frappe, "get_doc", return_value=doc),
			self.assertRaises(frappe.DoesNotExistError),
		):
			director_leads.get_director_lead("LEAD-1")

	def test_lead_reader_is_unscoped_only_for_the_full_board_profile(self):
		with patch.object(director_leads, "can_read_full_lead_board", return_value=True):
			self.assertIs(director_leads._lead_reader(), frappe.get_all)
		with patch.object(director_leads, "can_read_full_lead_board", return_value=False):
			self.assertIs(director_leads._lead_reader(), frappe.get_list)

	def test_lead_list_scope_uses_the_shared_group_team_condition(self):
		with (
			patch.object(director_leads, "can_read_full_lead_board", return_value=False),
			patch.object(
				director_leads,
				"get_student_list_read_condition",
				return_value="`tabCRM Lead`.owning_team in ('TEAM-1')",
			),
			patch.object(
				director_leads.frappe.db,
				"sql",
				return_value=[frappe._dict(name="LEAD-1"), frappe._dict(name="LEAD-2")],
			) as sql,
		):
			self.assertEqual(
				director_leads._list_scope_lead_ids(),
				["LEAD-1", "LEAD-2"],
			)

		sql.assert_called_once()

	def test_lead_sale_list_scope_is_unrestricted(self):
		with (
			patch.object(director_leads, "can_read_full_lead_board", return_value=True),
			patch.object(director_leads, "get_student_list_read_condition") as get_condition,
		):
			self.assertIsNone(director_leads._list_scope_lead_ids())

		get_condition.assert_not_called()

	def test_detail_endpoint_serves_routed_lead_to_the_full_board_profile(self):
		"""A Lead routed to another Team leaves the row scope but stays on the board."""
		doc = frappe._dict(name="LEAD-1", student_name="Nguyễn Minh An")
		doc.has_permission = lambda permission_type: False
		with (
			patch.object(director_leads, "_require_access"),
			patch.object(director_leads, "can_read_full_lead_board", return_value=True),
			patch.object(director_leads.frappe, "get_doc", return_value=doc),
			patch.object(director_leads.frappe.utils, "now_datetime", return_value="2026-09-08 10:00:00"),
			patch.object(director_leads, "_load_lookups", return_value={"statuses": {}}),
			patch.object(director_leads, "_event_projection", return_value=([], [])),
			patch.object(director_leads, "_lead_log", return_value=[]),
			patch.object(director_leads, "_map_detail_row", return_value={"id": "LEAD-1"}),
		):
			response = director_leads.get_director_lead("LEAD-1")

		self.assertEqual(response["lead"], {"id": "LEAD-1"})

	def test_event_projection_skips_unreadable_marketing_engagement(self):
		with (
			patch.object(director_leads, "_table_exists", return_value=True),
			patch.object(director_leads.frappe, "get_list", side_effect=frappe.PermissionError),
		):
			self.assertEqual(director_leads._event_projection("LEAD-1", {}), ([], []))

	def test_lead_log_maps_detailed_audit_events_without_dropping_source_fields(self):
		doc = frappe._dict(name="LEAD-1", owner="Administrator", creation="2026-09-07 10:00:00")
		with (
			patch.object(
				director_leads,
				"get_audit_logs_for_document",
				return_value=[
					{
						"event_id": "status:1",
						"category": "status",
						"event_type": "status_changed",
						"fieldname": "enrollment_status",
						"field_label": "Enrollment Status",
						"old_value": "Mới",
						"new_value": "Có triển vọng",
						"metadata": {"old_code": "NEW", "new_code": "PROSPECT"},
						"owner": "Administrator",
						"owner_full_name": "Administrator",
						"occurred_at": "2026-09-07 11:00:00",
						"source": "Status Change Log",
					}
				],
			),
			patch.object(director_leads, "_table_exists", return_value=False),
		):
			entries = director_leads._lead_log(doc, lookups={}, event_entries=[])

		self.assertEqual(len(entries), 1)
		self.assertEqual(entries[0]["title"], "Cập nhật tình trạng Lead")
		self.assertIn('từ "Mới" sang "Có triển vọng"', entries[0]["content"])
		self.assertEqual(entries[0]["event_type"], "status_changed")
		self.assertEqual(entries[0]["metadata"]["new_code"], "PROSPECT")
