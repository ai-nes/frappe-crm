"""Focused HTTP adapter tests for Lead processing commands."""

from unittest.mock import call, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import lead_processing
from crm.fcrm import lead_processing as lead_processing_service


class TestLeadProcessingAPI(FrappeTestCase):
	def test_status_endpoint_forwards_requested_status(self):
		expected = {
			"status": "PROCESSING",
			"resolution": "PENDING",
			"lead": "LEAD-2026-00001",
		}
		with patch.object(lead_processing, "_update_processing_status", return_value=expected) as command:
			self.assertEqual(
				lead_processing.update_processing_status(
					"LEAD-2026-00001", "PROCESSING", "Đang xử lý thủ công"
				),
				expected,
			)

		command.assert_called_once_with(
			lead="LEAD-2026-00001",
			status="PROCESSING",
			reason="Đang xử lý thủ công",
		)

	def test_assign_endpoint_resolves_public_lead_code(self):
		expected = {"status": "ASSIGNED", "lead": "HS-2026-HCM-000096"}
		with (
			patch.object(lead_processing, "_require_assignment_access"),
			patch.object(lead_processing, "resolve_lead_name", return_value="HS-2026-HCM-000096"),
			patch.object(lead_processing, "_assign_lead", return_value=expected) as command,
		):
			result = lead_processing.assign_lead(
				"LD-2026-HCM-000096",
				"STAFF-1",
				"TEAM-1",
				"Batch assignment",
				"assignment-1",
				0,
				"correlation-1",
			)

		self.assertEqual(result, expected)
		command.assert_called_once_with(
			lead="HS-2026-HCM-000096",
			owner_staff="STAFF-1",
			target_team_id="TEAM-1",
			reason="Batch assignment",
			idempotency_key="assignment-1",
			expected_revision=0,
			correlation_id="correlation-1",
		)

	def test_assignment_targets_endpoint_resolves_public_lead_code(self):
		expected = {
			"lead": "HS-2026-HCM-000096",
			"ownership_revision": 0,
			"targets": [],
		}
		with (
			patch.object(lead_processing, "_require_assignment_access"),
			patch.object(lead_processing, "resolve_lead_name", return_value="HS-2026-HCM-000096"),
			patch.object(
				lead_processing,
				"_list_lead_assignment_targets",
				return_value=expected,
			) as command,
		):
			result = lead_processing.list_lead_assignment_targets("LD-2026-HCM-000096")

		self.assertEqual(result, expected)
		command.assert_called_once_with(lead="HS-2026-HCM-000096")

	def test_assignment_target_service_scopes_recipients_to_the_lead(self):
		lead = frappe._dict(
			name="HS-2026-HCM-000097",
			processing_status="PROCESSED",
			province="Ho Chi Minh City",
			branch="FPTU Ho Chi Minh Campus",
			ownership_revision=2,
			owner_staff=None,
			assigned_to=None,
		)
		targets = [{"staff": "STAFF-1", "team": "TEAM-1"}]
		with (
			patch.object(lead_processing_service, "_load_lead", return_value=lead),
			patch.object(
				lead_processing_service,
				"list_province_recipients",
				return_value=targets,
			) as resolver,
		):
			result = lead_processing_service.list_lead_assignment_targets(lead.name)

		self.assertEqual(result["ownership_revision"], 2)
		self.assertEqual(result["targets"], targets)
		resolver.assert_called_once_with("Ho Chi Minh City", campus="FPTU Ho Chi Minh Campus")

	def test_assignment_target_service_rejects_only_new_and_closed_leads(self):
		base_lead = {
			"name": "HS-2026-HCM-000098",
			"province": "Ho Chi Minh City",
			"branch": "FPTU Ho Chi Minh Campus",
			"ownership_revision": 0,
			"owner_staff": None,
			"assigned_to": None,
		}
		for status in ("NEW", "CLOSED"):
			lead = frappe._dict({**base_lead, "processing_status": status})
			with patch.object(lead_processing_service, "_load_lead", return_value=lead):
				with self.assertRaises(lead_processing_service.LeadProcessingError) as ctx:
					lead_processing_service.list_lead_assignment_targets(lead.name)
			self.assertEqual(ctx.exception.code, "INVALID_STATUS")

	def test_assignment_target_service_allows_processing_and_assigned_leads(self):
		for status in ("PROCESSING", "PROCESSED", "ASSIGNED"):
			lead = frappe._dict(
				name="HS-2026-HCM-000099",
				processing_status=status,
				province="Ho Chi Minh City",
				branch="FPTU Ho Chi Minh Campus",
				ownership_revision=2,
				owner_staff="STAFF-1" if status == "ASSIGNED" else None,
				assigned_to="STAFF-1" if status == "ASSIGNED" else None,
			)
			targets = [{"staff": "STAFF-1", "team": "TEAM-1"}]
			with (
				patch.object(lead_processing_service, "_load_lead", return_value=lead),
				patch.object(lead_processing_service, "list_province_recipients", return_value=targets),
			):
				result = lead_processing_service.list_lead_assignment_targets(lead.name)

			self.assertEqual(result["targets"], targets)

	def test_bulk_endpoint_forwards_scan_scope(self):
		expected = {"summary": {"scanned": 2, "processed": 2}, "items": []}
		with patch.object(lead_processing, "_process_new_leads", return_value=expected) as command:
			self.assertEqual(lead_processing.process_new_leads("2026", 50), expected)

		command.assert_called_once_with(admission_year="2026", limit=50)

	def test_convert_endpoint_creates_a_student_from_an_assigned_lead(self):
		expected = {
			"status": "CLOSED",
			"resolution": "CREATED",
			"lead": "HS-2026-HCM-000001",
			"student": "STU-00001",
		}
		with (
			patch.object(lead_processing, "resolve_lead_name", return_value="HS-2026-HCM-000001"),
			patch.object(lead_processing.frappe, "generate_hash", return_value="request-1"),
			patch.object(lead_processing, "_handoff_lead", return_value=expected) as command,
		):
			result = lead_processing.convert_to_student("LD-2026-HCM-000001")

		self.assertEqual(result, expected)
		command.assert_called_once_with(
			lead="HS-2026-HCM-000001",
			idempotency_key="lead-convert:HS-2026-HCM-000001:request-1",
			correlation_id=None,
			_force_create=True,
		)

	def test_force_create_handoff_requires_an_assigned_lead(self):
		lead = frappe._dict(
			name="HS-2026-HCM-000002",
			processing_status="PROCESSED",
			resolution="PENDING",
		)
		with patch.object(lead_processing_service, "_load_lead", return_value=lead):
			with self.assertRaises(lead_processing_service.LeadProcessingError) as ctx:
				lead_processing_service.handoff_lead(
					lead.name,
					idempotency_key="convert-1",
					_force_create=True,
				)

		self.assertEqual(ctx.exception.code, "INVALID_STATUS")

	def test_force_create_handoff_persists_created_before_conversion(self):
		lead = frappe._dict(
			name="HS-2026-HCM-000003",
			processing_status="ASSIGNED",
			resolution="PENDING",
			phone="0900000000",
			province="Hồ Chí Minh",
			high_school="THPT-1",
			major="MAJOR-1",
			lifecycle_revision=0,
		)
		with (
			patch.object(lead_processing_service, "_load_lead", return_value=lead),
			patch.object(lead_processing_service.frappe, "get_roles", return_value=["Sale"]),
			patch.object(
				lead_processing_service,
				"convert_student",
				return_value={"target_student": "STU-00001"},
			) as convert,
			patch.object(lead_processing_service, "set_student_stage") as set_stage,
			patch.object(lead_processing_service, "_set_processing_values") as set_processing,
			patch.object(lead_processing_service.frappe.db, "commit"),
		):
			result = lead_processing_service.handoff_lead(
				lead.name,
				idempotency_key="convert-1",
				_force_create=True,
			)

		self.assertEqual(result["resolution"], "CREATED")
		self.assertEqual(result["student_stage"], "New")
		self.assertTrue(convert.call_args.kwargs["_lead_handoff"])
		set_processing.assert_has_calls(
			[
				call(lead.name, {"resolution": "CREATED"}),
				call(
					lead.name,
					{
						"processing_status": "CLOSED",
						"resolution": "CREATED",
						"resolution_reason": "CREATED handoff completed.",
					},
				),
			]
		)
		set_stage.assert_called_once_with("STU-00001", "New", _internal_service=True)

	def test_force_create_handoff_requires_a_sales_operator_role(self):
		lead = frappe._dict(
			name="HS-2026-HCM-000004",
			processing_status="ASSIGNED",
			resolution="PENDING",
		)
		with (
			patch.object(lead_processing_service, "_load_lead", return_value=lead),
			patch.object(
				lead_processing_service.frappe,
				"get_roles",
				return_value=["Admissions Director"],
			),
		):
			with self.assertRaises(lead_processing_service.LeadProcessingError) as ctx:
				lead_processing_service.handoff_lead(
					lead.name,
					idempotency_key="convert-2",
					_force_create=True,
				)

		self.assertEqual(ctx.exception.code, "FORBIDDEN")
