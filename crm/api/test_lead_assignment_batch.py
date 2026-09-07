from types import SimpleNamespace
from unittest import TestCase

from crm.api import lead_assignment_batch
from crm.api.lead_mapping import LeadMappingError


class TestLeadAssignmentBatchHelpers(TestCase):
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
