from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

import frappe

from crm.api import lead_assignment_batch
from crm.api.lead_mapping import LeadMappingError
from crm.fcrm import team_routing


class TestLeadAssignmentBatchHelpers(TestCase):
	class _BatchScope:
		target_team = None
		pool = None

		def get(self, key, default=None):
			return getattr(self, key, default)

	def test_resolve_batch_pool_prefers_lead_zone_mapping(self):
		mapped_pool = SimpleNamespace(name="POOL-ZONE", team="TEAM-ZONE", campus="CAMPUS-1")
		with (
			patch.object(
				lead_assignment_batch,
				"resolve_student_zone",
				return_value={"zone": "ZONE-1", "tier": 2},
			),
			patch.object(
				lead_assignment_batch,
				"zone_team_pool",
				return_value={"pool": "POOL-ZONE", "team": "TEAM-ZONE"},
			),
			patch.object(lead_assignment_batch, "_pool", return_value=mapped_pool),
			patch.object(lead_assignment_batch, "_validate_batch_pool", return_value=mapped_pool),
			patch.object(
				lead_assignment_batch.frappe,
				"get_all",
				side_effect=AssertionError("campus-wide pools must not be queried first"),
			),
		):
			result = lead_assignment_batch._resolve_batch_pool(
				self._BatchScope(),
				{"branch": "CAMPUS-1"},
				{"is_system_manager": True},
			)
		self.assertIs(result, mapped_pool)

	def test_target_team_rejects_zone_owned_by_another_team(self):
		batch = self._BatchScope()
		batch.target_team = "TEAM-TARGET"
		with (
			patch.object(
				lead_assignment_batch,
				"resolve_student_zone",
				return_value={"zone": "ZONE-1", "tier": 2},
			),
			patch.object(
				lead_assignment_batch,
				"zone_team_pool",
				return_value={"pool": "POOL-1", "team": "TEAM-ZONE"},
			),
			patch.object(
				lead_assignment_batch,
				"_team_scope",
				return_value={"name": "TEAM-TARGET", "groupProvince": "PROVINCE-1"},
			),
		):
			with self.assertRaises(frappe.ValidationError) as context:
				lead_assignment_batch._resolve_batch_pool(
					batch,
					{"branch": "CAMPUS-1"},
					{"is_system_manager": True},
				)
		self.assertEqual(context.exception.code, "TEAM_SCOPE_MISMATCH")

	def test_parse_list_deduplicates_string_json(self):
		self.assertEqual(
			lead_assignment_batch._parse_list('["LD-1", "LD-1", "LD-2"]', "lead_ids"),
			["LD-1", "LD-2"],
		)

	def test_queue_for_zone_preserves_province_queue_identity(self):
		lead = {"province": "PROVINCE-HCM"}
		self.assertEqual(
			lead_assignment_batch._queue_for_zone(lead, {"tier": 3}),
			"PROVINCE:PROVINCE-HCM",
		)

	def test_apply_result_keeps_routing_reason_and_capacity_fields(self):
		item = SimpleNamespace(
			name="ITEM-1",
			routing_tier=1,
			queue=None,
			owner_staff=None,
			team="TEAM-1",
			policy_version=None,
			routing_request=None,
			status="pending",
			reason="school_owner",
			execution_id=None,
			completed_at=None,
			error_code=None,
		)
		lead_assignment_batch._apply_result(
			item,
			{
				"status": "applied",
				"tier": 1,
				"owner_staff": "STAFF-1",
				"ownership": {"policy_version": "phase2-v1"},
			},
			"EXEC-1",
		)
		self.assertEqual(item.status, "assigned")
		self.assertEqual(item.owner_staff, "STAFF-1")
		self.assertEqual(item.policy_version, "phase2-v1")
		self.assertIn("school_owner", item.reason)

	def test_run_unassigned_returns_no_work_without_creating_a_batch(self):
		with (
			patch.object(lead_assignment_batch, "_require_access", return_value={}),
			patch.object(lead_assignment_batch, "_unassigned_lead_names", return_value=[]),
		):
			result = lead_assignment_batch.run_unassigned_lead_assignment()

		self.assertEqual(result["status"], "no_work")
		self.assertIsNone(result["batch"])
		self.assertEqual(result["items"], [])

	def test_run_unassigned_keeps_internal_batch_as_audit_record(self):
		batch = SimpleNamespace(name="BATCH-1")
		with (
			patch.object(lead_assignment_batch, "_require_access", return_value={}),
			patch.object(
				lead_assignment_batch,
				"_unassigned_lead_names",
				return_value=["LEAD-1", "LEAD-2"],
			),
			patch.object(lead_assignment_batch, "_new_unassigned_lead_batch", return_value=batch),
			patch.object(
				lead_assignment_batch,
				"run_lead_assignment_batch",
				return_value={"status": "completed", "items": []},
			),
		):
			result = lead_assignment_batch.run_unassigned_lead_assignment()

		self.assertEqual(result["status"], "completed")
		self.assertEqual(result["scanned"], 2)
		self.assertEqual(result["trigger"], "unassigned_leads")

	def test_handoff_assigned_lead_uses_revision_and_batch_idempotency(self):
		lead = frappe._dict(name="LEAD-1", lifecycle_revision=7)
		conversion = {"status": "CLOSED", "student": "STUDENT-1"}
		with (
			patch.object(lead_assignment_batch.frappe, "get_doc", return_value=lead),
			patch.object(lead_assignment_batch, "handoff_lead", return_value=conversion) as handoff,
		):
			result = lead_assignment_batch._handoff_assigned_lead("LEAD-1", "BATCH-1", "ITEM-1", "EXEC-1")

		self.assertEqual(result, conversion)
		# The batch authorized its operator already; the conversion runs as an
		# internal service because the committed owner may sit outside that scope.
		handoff.assert_called_once_with(
			lead="LEAD-1",
			expected_lifecycle_revision=7,
			idempotency_key="lead-assignment-conversion:BATCH-1:ITEM-1:7",
			correlation_id="EXEC-1:ITEM-1:conversion",
			_internal_service=True,
		)

	def test_converted_student_id_reads_handoff_envelope_and_command_result(self):
		self.assertEqual(
			lead_assignment_batch._converted_student_id(
				{"status": "CLOSED", "student": "STUDENT-1", "conversion": {"target_student": "STUDENT-1"}}
			),
			"STUDENT-1",
		)
		self.assertEqual(
			lead_assignment_batch._converted_student_id({"conversion": {"student_id": "STUDENT-2"}}),
			"STUDENT-2",
		)
		self.assertEqual(lead_assignment_batch._converted_student_id({}), "—")

	def test_batch_recipient_forwards_in_run_load_overrides(self):
		batch = self._BatchScope()
		lead = frappe._dict(name="LEAD-1", province="Ho Chi Minh City", branch="CAMPUS-1")
		overrides = {"STAFF-1": 1}
		with (
			patch.object(lead_assignment_batch, "_canonical_province", return_value="Ho Chi Minh City"),
			patch.object(lead_assignment_batch, "_validate_batch_scope", return_value=None),
			patch.object(
				lead_assignment_batch,
				"select_province_recipient",
				return_value={"ownerStaff": "STAFF-2"},
			) as select,
		):
			lead_assignment_batch._resolve_batch_recipient(batch, lead, {}, load_overrides=overrides)

		select.assert_called_once_with(
			"Ho Chi Minh City",
			campus="CAMPUS-1",
			team_id=None,
			load_overrides=overrides,
		)

	def test_batch_import_requires_school_and_major_headers(self):
		with self.assertRaises(LeadMappingError) as context:
			lead_assignment_batch._parse_batch_import_rows(
				None,
				"Họ và tên,Số điện thoại,Tỉnh/Thành phố,Nguồn\n"
				"Nguyễn Văn A,0900000000,Ho Chi Minh City,Website\n",
			)
		self.assertEqual(context.exception.code, "CSV_MISSING_HEADERS")

	def test_batch_import_accepts_catalog_headers_and_cccd_alias(self):
		rows = lead_assignment_batch._parse_batch_import_rows(
			None,
			"Họ và tên,Số điện thoại,Tỉnh/Thành phố,Trường THPT,Ngành quan tâm,Nguồn,CCCD\n"
			"Nguyễn Văn A,0900000000,Ho Chi Minh City,THPT A,Công nghệ thông tin,Website,012345678901\n",
		)
		self.assertEqual(rows[0]["high_school"], "THPT A")
		self.assertEqual(rows[0]["major"], "Công nghệ thông tin")
		self.assertEqual(rows[0]["id_number"], "012345678901")

	def test_province_selection_uses_all_eligible_teams_and_current_load(self):
		teams = [
			{
				"name": "TEAM-NORTH",
				"team_name": "Đội Tư vấn Khu Bắc",
				"campus": "CAMPUS-1",
			},
			{
				"name": "TEAM-SOUTH",
				"team_name": "Đội Tư vấn Khu Nam",
				"campus": "CAMPUS-1",
			},
		]
		recipients = {
			"TEAM-NORTH": [
				{
					"staff": "STAFF-NORTH",
					"staffName": "Nguyễn Minh Khôi",
					"team": "TEAM-NORTH",
					"function": "Sale",
					"capacity": {"active": 2, "limit": 10, "remaining": 8},
				}
			],
			"TEAM-SOUTH": [
				{
					"staff": "STAFF-SOUTH",
					"staffName": "Lê Thanh Hương",
					"team": "TEAM-SOUTH",
					"function": "CTV Sale",
					"capacity": {"active": 0, "limit": 10, "remaining": 10},
				}
			],
		}
		with (
			patch.object(team_routing, "_active_teams_for_province", return_value=teams),
			patch.object(
				team_routing,
				"team_routing_readiness",
				return_value={"status": "ready", "reason": "ready"},
			),
			patch.object(
				team_routing,
				"_active_team_recipients",
				side_effect=lambda team_id, at=None: recipients[team_id],
			),
		):
			result = team_routing.select_province_recipient(
				"Ho Chi Minh City",
				load_overrides={"STAFF-SOUTH": 2},
			)

		self.assertEqual(result["team"], "TEAM-NORTH")
		self.assertEqual(result["ownerStaff"], "STAFF-NORTH")
		self.assertEqual(result["function"], "Sale")
		self.assertEqual(result["policyVersion"], "province-capacity-v1")

	class _RetryItem:
		"""Minimal stand-in for one batch child row."""

		def __init__(self, status, error_code):
			self.name = "ITEM-1"
			self.lead = "HS-1"
			self.status = status
			self.error_code = error_code

	def _is_retryable(self, item, processing_status):
		frappe_stub = MagicMock()
		frappe_stub.db.get_value.return_value = processing_status
		with patch.object(lead_assignment_batch, "frappe", frappe_stub):
			return lead_assignment_batch._retryable_item(item)

	def test_retry_skips_permanent_failure_while_lead_stays_closed(self):
		item = self._RetryItem("manual_review", "MISSING_PROVINCE")
		self.assertFalse(self._is_retryable(item, "CLOSED"))

	def test_retry_accepts_permanent_failure_once_lead_is_reopened(self):
		item = self._RetryItem("manual_review", "MISSING_PROVINCE")
		self.assertTrue(self._is_retryable(item, "PROCESSED"))

	def test_retry_accepts_routing_review_failure_without_reopening(self):
		item = self._RetryItem("manual_review", "NO_ELIGIBLE_RECIPIENT")
		self.assertTrue(self._is_retryable(item, "PROCESSED"))

	def test_retry_leaves_already_assigned_items_alone(self):
		item = self._RetryItem("assigned", None)
		self.assertFalse(self._is_retryable(item, "ASSIGNED"))
