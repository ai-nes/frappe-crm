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

	def test_live_closed_lead_with_routing_error_is_serialized_for_manual_review(self):
		item = lead_assignment_batch._serialize_live_review_item(
			frappe._dict(
				name="LEAD-CLOSED-1",
				student_name="Nguyễn Văn A",
				phone="0900000000",
				province=None,
				high_school="SCHOOL-1",
				major="MAJOR-1",
				resolution="PENDING",
				resolution_reason="Lead bị đóng: thiếu tỉnh.",
				modified="2026-09-09 10:00:00",
				creation="2026-09-09 09:00:00",
			)
		)

		self.assertEqual(item["status"], "manual_review")
		self.assertEqual(item["batchId"], "")
		self.assertEqual(item["leadId"], "LEAD-CLOSED-1")
		self.assertEqual(item["missingFields"], ["Tỉnh"])
		self.assertEqual(item["reason"], "Đã đóng hồ sơ vì: Thiếu tỉnh/thành phố.")

	def test_live_closed_lead_reason_lists_only_actual_missing_fields(self):
		item = lead_assignment_batch._serialize_live_review_item(
			frappe._dict(
				name="LEAD-CLOSED-2",
				student_name="Hà Tuấn Kiệt",
				phone="0903000014",
				province=None,
				high_school=None,
				major="MAJOR-1",
				resolution="PENDING",
				resolution_reason=(
					"Đã đóng hồ sơ vì thiếu số điện thoại, tỉnh/thành phố, trường THPT hoặc ngành quan tâm."
				),
			)
		)

		self.assertEqual(item["missingFields"], ["Tỉnh"])
		self.assertEqual(
			item["reason"],
			"Đã đóng hồ sơ vì: Thiếu tỉnh/thành phố.",
		)

	def test_queue_for_zone_preserves_province_queue_identity(self):
		lead = {"province": "PROVINCE-HCM"}
		self.assertEqual(
			lead_assignment_batch._queue_for_zone(lead, {"tier": 3}),
			"PROVINCE:PROVINCE-HCM",
		)

	def test_assignment_workflow_maps_latest_batch_summary_to_steps(self):
		class WorkflowBatch(SimpleNamespace):
			def get(self, key, default=None):
				return getattr(self, key, default)

		batch = WorkflowBatch(
			name="BATCH-1",
			batch_name="Phân công Lead 1",
			description="Scan Lead chưa có người phụ trách",
			status="completed_with_errors",
			items=[
				frappe._dict(status="assigned"),
				frappe._dict(status="manual_review"),
				frappe._dict(status="failed"),
			],
			creation="2026-09-08 10:00:00",
			modified="2026-09-08 10:01:00",
			previewed_at=None,
			completed_at="2026-09-08 10:01:00",
		)

		workflow = lead_assignment_batch._serialize_assignment_workflow(batch)
		steps = {step["id"]: step for step in workflow["steps"]}

		self.assertTrue(workflow["hasRun"])
		self.assertTrue(workflow["hasData"])
		self.assertEqual(workflow["pendingCount"], 0)
		self.assertEqual(workflow["batch"]["summary"]["total"], 3)
		self.assertEqual(steps["validation"]["metrics"]["successCount"], 2)
		self.assertEqual(steps["review"]["metrics"]["processedCount"], 2)
		self.assertEqual(steps["review"]["status"], "warning")
		self.assertEqual(steps["assignment"]["metrics"]["successCount"], 1)

	def test_assignment_workflow_without_batch_is_idle_and_empty(self):
		workflow = lead_assignment_batch._serialize_assignment_workflow()

		self.assertFalse(workflow["hasRun"])
		self.assertFalse(workflow["hasData"])
		self.assertEqual(workflow["pendingCount"], 0)
		self.assertIsNone(workflow["batch"])
		self.assertTrue(all(step["status"] == "idle" for step in workflow["steps"]))
		self.assertTrue(all(step["metrics"]["processedCount"] == 0 for step in workflow["steps"]))

	def test_assignment_workflow_projects_current_processed_leads(self):
		with (
			patch.object(
				lead_assignment_batch.frappe,
				"get_list",
				return_value=[
					frappe._dict(name="LEAD-1", processing_status="PROCESSED", owner_staff=None, assigned_to=None),
					frappe._dict(name="LEAD-2", processing_status="ASSIGNED", owner_staff="SALE-1", assigned_to=None),
					frappe._dict(
						name="LEAD-3",
						processing_status="CLOSED",
						resolution="INVALID",
						owner_staff=None,
						assigned_to=None,
					),
				],
			),
			patch.object(
				lead_assignment_batch,
				"list_lead_assignment_batches",
				return_value={"items": [], "pagination": {"has_next_page": False}},
			),
		):
			summary = lead_assignment_batch._processing_workflow_summary()

		workflow = lead_assignment_batch._serialize_assignment_workflow(summary=summary)
		steps = {step["id"]: step for step in workflow["steps"]}

		self.assertFalse(workflow["hasRun"])
		self.assertTrue(workflow["hasData"])
		self.assertEqual(workflow["pendingCount"], 1)
		self.assertEqual(summary["total"], 3)
		self.assertEqual(summary["valid"], 3)
		self.assertEqual(summary["pending"], 1)
		self.assertEqual(summary["assigned"], 1)
		self.assertEqual(summary["invalid"], 0)
		self.assertEqual(steps["classification"]["status"], "success")
		self.assertEqual(steps["matching"]["status"], "running")
		self.assertEqual(steps["review"]["status"], "warning")

	def test_history_status_follows_live_assigned_lead(self):
		self.assertEqual(
			lead_assignment_batch._effective_history_item_status("pending", "ASSIGNED"),
			"assigned",
		)

	def test_history_status_projects_closed_lead_to_skipped(self):
		self.assertEqual(
			lead_assignment_batch._effective_history_item_status("pending", "CLOSED", "DUPLICATE"),
			"skipped",
		)

	def test_history_status_keeps_routing_attention_state_for_open_lead(self):
		self.assertEqual(
			lead_assignment_batch._effective_history_item_status("failed", "PROCESSED"),
			"failed",
		)

	def test_workflow_summary_keeps_assigned_history_after_scope_changes(self):
		batch = SimpleNamespace(
			items=[
				frappe._dict(lead="LEAD-ASSIGNED", status="pending"),
				frappe._dict(lead="LEAD-REVIEW", status="manual_review"),
			]
		)
		lead_states = {
			"LEAD-ASSIGNED": frappe._dict(
				processing_status="ASSIGNED", owner_staff="SALE-1", assigned_to=None
			),
			"LEAD-REVIEW": frappe._dict(
				processing_status="CLOSED", resolution="DUPLICATE", owner_staff=None, assigned_to=None
			),
		}
		with (
			patch.object(
				lead_assignment_batch,
				"list_lead_assignment_batches",
				return_value={"items": [{"name": "BATCH-1"}], "pagination": {"has_next_page": False}},
			),
			patch.object(lead_assignment_batch.frappe, "get_doc", return_value=batch),
			patch.object(
				lead_assignment_batch.frappe.db,
				"get_value",
				side_effect=lambda _doctype, name, _fields, **_kwargs: lead_states[name],
			),
			patch.object(lead_assignment_batch.frappe, "get_list", return_value=[]),
		):
			summary = lead_assignment_batch._processing_workflow_summary()

		self.assertEqual(summary["total"], 2)
		self.assertEqual(summary["valid"], 2)
		self.assertEqual(summary["assigned"], 1)
		self.assertEqual(summary["manualReview"], 0)
		self.assertEqual(summary["skipped"], 1)

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
		lock = MagicMock()
		lock.acquire.return_value = True
		with (
			patch.object(lead_assignment_batch, "_require_access", return_value={}),
			patch.object(lead_assignment_batch, "_unassigned_lead_names", return_value=[]),
			patch.object(lead_assignment_batch, "_assignment_run_lock", return_value=lock),
		):
			result = lead_assignment_batch.run_unassigned_lead_assignment()

		self.assertEqual(result["status"], "no_work")
		self.assertIsNone(result["batch"])
		self.assertEqual(result["items"], [])

	def test_run_unassigned_keeps_internal_batch_as_audit_record(self):
		batch = SimpleNamespace(name="BATCH-1")
		lock = MagicMock()
		lock.acquire.return_value = True
		with (
			patch.object(lead_assignment_batch, "_require_access", return_value={}),
			patch.object(lead_assignment_batch, "_assignment_run_lock", return_value=lock),
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

	def test_unassigned_scan_returns_busy_without_starting_another_batch(self):
		lock = MagicMock()
		lock.acquire.return_value = False
		with (
			patch.object(lead_assignment_batch, "_assignment_run_lock", return_value=lock),
			patch.object(
				lead_assignment_batch,
				"_unassigned_lead_names",
				side_effect=AssertionError("busy scans must not query Leads"),
			),
		):
			result = lead_assignment_batch._run_unassigned_lead_assignment(
				{},
				trigger="scheduled_unassigned_leads",
				blocking=False,
				blocking_timeout=None,
			)

		self.assertEqual(result["status"], "busy")
		self.assertIsNone(result["batch"])
		lock.release.assert_not_called()

	def test_unassigned_scan_can_filter_leads_older_than_worker_delay(self):
		lead = frappe._dict(
			name="LEAD-1",
			owner_staff=None,
			assigned_to=None,
			converted_student=None,
			resolution="PENDING",
		)
		with (
			patch.object(
				lead_assignment_batch.frappe,
				"get_all",
				return_value=[lead],
			) as get_all,
			patch.object(lead_assignment_batch, "_lead", return_value=lead),
			patch.object(lead_assignment_batch, "add_to_date", return_value="CUTOFF"),
		):
			result = lead_assignment_batch._unassigned_lead_names({}, min_age_minutes=5)

		self.assertEqual(result, ["LEAD-1"])
		self.assertEqual(
			get_all.call_args.kwargs["filters"],
			{"processing_status": "PROCESSED", "modified": ["<=", "CUTOFF"]},
		)

	def test_scheduled_unassigned_scan_uses_administrator_and_nonblocking_lock(self):
		expected = {"status": "no_work", "batch": None}
		previous_user = getattr(lead_assignment_batch.frappe.session, "user", None) or "Guest"
		with (
			patch.object(lead_assignment_batch.frappe, "set_user") as set_user,
			patch.object(lead_assignment_batch, "_require_access", return_value={}),
			patch.object(
				lead_assignment_batch,
				"_run_unassigned_lead_assignment",
				return_value=expected,
			) as run_scan,
		):
			result = lead_assignment_batch.run_scheduled_unassigned_lead_assignment()

		self.assertIs(result, expected)
		set_user.assert_any_call("Administrator")
		self.assertEqual(set_user.call_args_list[-1].args, (previous_user,))
		run_scan.assert_called_once_with(
			{},
			trigger="scheduled_unassigned_leads",
			blocking=False,
			blocking_timeout=None,
		)

	def test_manual_unassigned_scan_ignores_configured_wait_time(self):
		expected = {"status": "no_work", "batch": None}
		with (
			patch.object(lead_assignment_batch, "_require_access", return_value={}),
			patch.object(
				lead_assignment_batch,
				"_run_unassigned_lead_assignment",
				return_value=expected,
			) as run_scan,
		):
			result = lead_assignment_batch.run_unassigned_lead_assignment()

		self.assertIs(result, expected)
		run_scan.assert_called_once_with(
			{},
			trigger="unassigned_leads",
			blocking=True,
			blocking_timeout=10,
			min_age_minutes=0,
		)

	def test_scheduled_unassigned_scan_uses_workflow_input_settings(self):
		config = {
			"stored": {
				"input": {
					"enabled": True,
					"scheduledMinAgeMinutes": 12,
					"maxLeadsPerRun": 7,
				},
				"classification": {"enabled": True},
				"review": {"maxRetries": 3},
			}
		}
		lock = MagicMock()
		lock.acquire.return_value = True
		with (
			patch.object(lead_assignment_batch, "get_workflow_config", return_value=config),
			patch.object(lead_assignment_batch, "_assignment_run_lock", return_value=lock),
			patch.object(lead_assignment_batch, "_unassigned_lead_names", return_value=[]) as scan,
		):
			result = lead_assignment_batch._run_unassigned_lead_assignment(
				{},
				trigger="scheduled_unassigned_leads",
				blocking=False,
				blocking_timeout=None,
			)

		self.assertEqual(result["status"], "no_work")
		self.assertEqual(
			scan.call_args.kwargs,
			{"min_age_minutes": 12, "limit": 7},
		)

	def test_disabled_input_step_skips_scheduler_before_lock(self):
		config = {"stored": {"input": {"enabled": False}}}
		with (
			patch.object(lead_assignment_batch, "get_workflow_config", return_value=config),
			patch.object(
				lead_assignment_batch,
				"_assignment_run_lock",
				side_effect=AssertionError("disabled workflow must not acquire a lock"),
			),
		):
			result = lead_assignment_batch._run_unassigned_lead_assignment(
				{},
				trigger="scheduled_unassigned_leads",
				blocking=False,
				blocking_timeout=None,
			)

		self.assertEqual(result["status"], "disabled")

	def test_disabled_classification_uses_saved_processing_result(self):
		lead = frappe._dict(
			name="LEAD-STORED-RESULT",
			processing_status="PROCESSED",
			resolution="PENDING",
			resolution_reason="Đã xử lý trước đó",
			student_name="Nguyễn Văn A",
			phone="0900000000",
			province="PROVINCE-1",
			owner_staff=None,
			assigned_to=None,
			converted_student=None,
			ownership_revision=1,
		)
		item = frappe._dict(
			status="pending",
			retry_count=0,
			error_code=None,
			owner_staff=None,
		)
		recipient = {
			"reason": "Đã dùng kết quả xử lý Lead đã lưu.",
			"team": "TEAM-1",
			"ownerStaff": "STAFF-1",
			"capacity": {"active": 1, "limit": 10, "remaining": 9},
			"policyVersion": "lead-routing-v1",
		}
		with (
			patch.object(lead_assignment_batch, "_batch_item_lead", return_value=lead),
			patch.object(lead_assignment_batch, "_validate_batch_scope"),
			patch.object(lead_assignment_batch, "preview_lead") as preview,
			patch.object(lead_assignment_batch, "_resolve_batch_recipient", return_value=recipient),
		):
			lead_assignment_batch._preview_item(
				self._BatchScope(),
				item,
				{},
				workflow_config={
					"stored": {
						"classification": {"enabled": False},
					}
				},
			)

		preview.assert_not_called()
		self.assertEqual(item.status, "pending")
		self.assertEqual(item.owner_staff, "STAFF-1")
		self.assertEqual(item.reason, recipient["reason"])

	def test_retry_is_blocked_when_batch_item_reaches_snapshot_limit(self):
		class RetryBatch(SimpleNamespace):
			def get(self, key, default=None):
				return getattr(self, key, default)

		batch = RetryBatch(
			name="BATCH-RETRY",
			workflow_config_snapshot={
				"version": "lead-assignment-workflow-v2",
				"stored": {"review": {"maxRetries": 2}},
			},
			items=[
				frappe._dict(
					name="ITEM-1",
					status="manual_review",
					error_code="NO_ELIGIBLE_RECIPIENT",
					retry_count=2,
				)
			],
		)
		with (
			patch.object(lead_assignment_batch, "_require_access", return_value={}),
			patch.object(lead_assignment_batch.frappe, "get_doc", return_value=batch),
			patch.object(lead_assignment_batch, "_save_batch"),
			patch.object(lead_assignment_batch.frappe.db, "commit"),
			patch.object(
				lead_assignment_batch,
				"_serialize_batch",
				return_value={"status": "completed_with_errors"},
			) as serialize,
		):
			result = lead_assignment_batch.retry_lead_assignment_batch("BATCH-RETRY")

		self.assertEqual(result, {"status": "completed_with_errors"})
		self.assertEqual(batch.items[0].retry_count, 2)
		self.assertEqual(batch.items[0].error_code, "RETRY_LIMIT_REACHED")
		serialize.assert_called_once_with(batch)

	def test_first_run_persists_workflow_and_routing_policy_snapshot(self):
		class RunBatch(SimpleNamespace):
			def get(self, key, default=None):
				return getattr(self, key, default)

		batch = RunBatch(
			name="BATCH-SNAPSHOT",
			batch_name="Batch snapshot",
			status="ready",
			province=None,
			target_team=None,
			pool=None,
			source="manual",
			description="Snapshot test",
			created_by="Administrator",
			execution_id=None,
			workflow_config_version=None,
			workflow_config_snapshot=None,
			started_at=None,
			completed_at=None,
			items=[],
			total_count=0,
			assigned_count=0,
			deferred_count=0,
			manual_review_count=0,
			failed_count=0,
		)
		batch.reload = lambda: None
		workflow_config = {
			"schemaVersion": "lead-assignment-workflow-v1",
			"version": "lead-assignment-workflow-v6",
			"revision": 6,
			"stored": {
				"input": {"enabled": True, "scheduledMinAgeMinutes": 5, "maxLeadsPerRun": 1000},
				"classification": {"enabled": True},
				"review": {"maxRetries": 3},
			},
		}
		policy = {
			"version": "lead-routing-v9",
			"layerOrder": ["campaign", "group", "global"],
			"layers": [],
		}
		with (
			patch.object(lead_assignment_batch, "_require_access", return_value={}),
			patch.object(lead_assignment_batch.frappe, "get_doc", return_value=batch),
			patch.object(lead_assignment_batch, "get_workflow_config", return_value=workflow_config),
			patch.object(lead_assignment_batch, "get_lead_routing_policy", return_value=policy),
			patch.object(lead_assignment_batch, "_preview_batch_items"),
			patch.object(lead_assignment_batch, "_save_batch"),
			patch.object(lead_assignment_batch.frappe.db, "commit"),
		):
			lead_assignment_batch.run_lead_assignment_batch(batch.name)

		self.assertEqual(batch.workflow_config_version, "lead-assignment-workflow-v6")
		self.assertEqual(
			batch.workflow_config_snapshot["matching"]["routingPolicy"], policy
		)

	def test_assignment_batch_has_no_student_handoff_helper(self):
		self.assertFalse(hasattr(lead_assignment_batch, "_handoff_assigned_lead"))
		self.assertFalse(hasattr(lead_assignment_batch, "_converted_student_id"))

	def test_batch_recipient_forwards_in_run_load_overrides(self):
		batch = self._BatchScope()
		lead = frappe._dict(name="LEAD-1", province="Ho Chi Minh City", branch="CAMPUS-1")
		overrides = {"STAFF-1": 1}
		policy = {"enabled": True, "version": "lead-routing-v1"}
		with (
			patch.object(lead_assignment_batch, "_canonical_province", return_value="Ho Chi Minh City"),
			patch.object(lead_assignment_batch, "_validate_batch_scope", return_value=None),
			patch.object(
				lead_assignment_batch,
				"resolve_lead_recipient",
				return_value={"ownerStaff": "STAFF-2"},
			) as resolve,
		):
			lead_assignment_batch._resolve_batch_recipient(
				batch, lead, {}, load_overrides=overrides, policy=policy
			)

		resolve.assert_called_once_with(
			lead,
			policy=policy,
			province="Ho Chi Minh City",
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

	def test_batch_import_accepts_missing_optional_cccd(self):
		rows = lead_assignment_batch._parse_batch_import_rows(
			None,
			"Họ và tên,Số điện thoại,Tỉnh/Thành phố,Trường THPT,Ngành quan tâm,Nguồn\n"
			"Nguyễn Văn A,0900000000,Ho Chi Minh City,THPT A,Công nghệ thông tin,Website\n",
		)
		self.assertNotIn("id_number", rows[0])

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
					"capacity": {"active": 2, "limit": 10, "remaining": 8, "configured": True},
				}
			],
			"TEAM-SOUTH": [
				{
					"staff": "STAFF-SOUTH",
					"staffName": "Lê Thanh Hương",
					"team": "TEAM-SOUTH",
					"function": "CTV Sale",
					"capacity": {"active": 0, "limit": 10, "remaining": 10, "configured": True},
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
				"_team_recipient_pool",
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

	def test_province_selection_rejects_staff_with_no_capacity_configured(self):
		"""A Sale/CTV who has never been given a capacity period is not eligible.

		This is a deliberate business rule, not a display default: missing
		capacity used to mean "unlimited", but now means "cannot receive any
		Lead until an admin sets it up" — and the failure message must name
		that cause distinctly from "everyone is full".
		"""
		teams = [{"name": "TEAM-NORTH", "team_name": "Đội Tư vấn Khu Bắc", "campus": "CAMPUS-1"}]
		recipients = {
			"TEAM-NORTH": [
				{
					"staff": "STAFF-NORTH",
					"staffName": "Nguyễn Minh Khôi",
					"team": "TEAM-NORTH",
					"function": "Sale",
					"capacity": {"active": 0, "limit": None, "remaining": None, "configured": False},
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
				"_team_recipient_pool",
				side_effect=lambda team_id, at=None: recipients[team_id],
			),
		):
			with self.assertRaises(frappe.ValidationError) as ctx:
				team_routing.select_province_recipient("Ho Chi Minh City")
		self.assertIn("thiết lập capacity", str(ctx.exception))
		self.assertIn("Nguyễn Minh Khôi", str(ctx.exception))
		self.assertEqual(ctx.exception.code, "STAFF_CAPACITY_NOT_CONFIGURED")

	def test_fallback_recipient_selects_team_lead_when_no_sale_or_ctv_active(self):
		teams = [{"name": "TEAM-NORTH", "team_name": "Đội Tư vấn Khu Bắc", "campus": "CAMPUS-1"}]
		lead_membership = frappe._dict(staff="STAFF-LEAD", function="Lead Sale")

		def get_value_side_effect(doctype, *args, **kwargs):
			if doctype == "CRM Team":
				return "STAFF-LEAD"
			if doctype == "CRM Staff":
				return frappe._dict(name="STAFF-LEAD", full_name="Trưởng nhóm Bắc", user="lead@x.com")
			if doctype == "User":
				return 1
			return None

		with (
			patch.object(team_routing, "_active_teams_for_province", return_value=teams),
			patch.object(team_routing.frappe, "get_all", return_value=[frappe._dict(name="STAFF-LEAD")]),
			patch.object(team_routing.frappe.db, "get_value", side_effect=get_value_side_effect),
			patch.object(team_routing, "_active_memberships", return_value=[lead_membership]),
			patch.object(team_routing, "active_lead_count", return_value=0),
		):
			result = team_routing.select_province_fallback_recipient("Ho Chi Minh City")

		self.assertEqual(result["ownerStaff"], "STAFF-LEAD")
		self.assertEqual(result["team"], "TEAM-NORTH")
		self.assertEqual(result["function"], "Lead Sale")
		self.assertTrue(result["fallback"])

	def test_fallback_recipient_fails_when_no_team_has_an_active_team_lead(self):
		teams = [{"name": "TEAM-NORTH", "team_name": "Đội Tư vấn Khu Bắc", "campus": "CAMPUS-1"}]
		with (
			patch.object(team_routing, "_active_teams_for_province", return_value=teams),
			patch.object(team_routing.frappe, "get_all", return_value=[]),
			patch.object(team_routing.frappe.db, "get_value", return_value=None),
			patch.object(team_routing, "_active_memberships", return_value=[]),
		):
			with self.assertRaises(frappe.ValidationError) as context:
				team_routing.select_province_fallback_recipient("Ho Chi Minh City")
		self.assertEqual(context.exception.code, "NO_ELIGIBLE_RECIPIENT")

	def test_batch_recipient_does_not_fall_back_to_team_lead_when_no_eligible_recipient(self):
		batch = self._BatchScope()
		lead = frappe._dict(name="LEAD-1", province="Ho Chi Minh City", branch="CAMPUS-1")
		no_eligible = frappe.ValidationError("Không có Team đủ điều kiện: TEAM-1: chưa có Sale/CTV.")
		no_eligible.code = "NO_ELIGIBLE_RECIPIENT"
		policy = {"enabled": True, "version": "lead-routing-v1"}
		with (
			patch.object(lead_assignment_batch, "_canonical_province", return_value="Ho Chi Minh City"),
			patch.object(lead_assignment_batch, "_validate_batch_scope", return_value=None),
			patch.object(
				lead_assignment_batch,
				"resolve_lead_recipient",
				side_effect=no_eligible,
			) as resolve,
		):
			with self.assertRaises(frappe.ValidationError) as context:
				lead_assignment_batch._resolve_batch_recipient(batch, lead, {}, policy=policy)

		resolve.assert_called_once()
		self.assertEqual(context.exception.code, "NO_ELIGIBLE_RECIPIENT")

	def test_batch_recipient_allows_global_layer_when_province_is_missing(self):
		batch = self._BatchScope()
		lead = frappe._dict(name="LEAD-1", province=None, branch="CAMPUS-1")
		policy = {"enabled": True, "version": "lead-routing-v1"}
		recipient = {"ownerStaff": "STAFF-1", "team": "TEAM-1"}
		with (
			patch.object(lead_assignment_batch, "_canonical_province", return_value=None),
			patch.object(lead_assignment_batch, "_validate_batch_scope", return_value=None),
			patch.object(
				lead_assignment_batch,
				"resolve_lead_recipient",
				return_value=recipient,
			) as resolve,
		):
			result = lead_assignment_batch._resolve_batch_recipient(batch, lead, {}, policy=policy)

		self.assertIs(result, recipient)
		self.assertIsNone(resolve.call_args.kwargs["province"])

	def test_batch_recipient_does_not_fall_back_when_capacity_not_configured(self):
		"""Missing capacity must land in manual_review, not silently on the Trưởng nhóm.

		This is the exact regression the "chưa thiết lập capacity" fix guards
		against: STAFF_CAPACITY_NOT_CONFIGURED is a distinct code from
		NO_ELIGIBLE_RECIPIENT precisely so this batch resolver re-raises it
		instead of calling the fallback — a stand-in team lead would otherwise
		mask the fact that nobody eligible was ever configured to receive Leads.
		"""
		batch = self._BatchScope()
		lead = frappe._dict(name="LEAD-1", province="Ho Chi Minh City", branch="CAMPUS-1")
		not_configured = frappe.ValidationError(
			"Team có Sale/CTV nhưng chưa ai được thiết lập capacity: Nguyễn Minh Khôi."
		)
		not_configured.code = "STAFF_CAPACITY_NOT_CONFIGURED"
		policy = {"enabled": True, "version": "lead-routing-v1"}
		with (
			patch.object(lead_assignment_batch, "_canonical_province", return_value="Ho Chi Minh City"),
			patch.object(lead_assignment_batch, "_validate_batch_scope", return_value=None),
			patch.object(
				lead_assignment_batch,
				"resolve_lead_recipient",
				side_effect=not_configured,
			),
		):
			with self.assertRaises(frappe.ValidationError) as context:
				lead_assignment_batch._resolve_batch_recipient(batch, lead, {}, policy=policy)
		self.assertEqual(context.exception.code, "STAFF_CAPACITY_NOT_CONFIGURED")

	def test_reset_item_expands_bare_error_code_into_a_specific_reason(self):
		item = MagicMock()
		lead_assignment_batch._reset_item(item, status="manual_review", reason="NOT_PROCESSED")
		self.assertEqual(item.reason, "Lead chưa qua bước Xử lý Lead nên chưa thể phân công.")

	def test_reset_item_keeps_a_specific_message_untouched(self):
		item = MagicMock()
		specific = "Không có Team đủ điều kiện: Đội Bắc: Team chưa có Sale hoặc CTV Sale đang hoạt động."
		lead_assignment_batch._reset_item(item, status="manual_review", reason=specific)
		self.assertEqual(item.reason, specific)

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

	def test_retry_keeps_missing_province_review_retryable(self):
		item = self._RetryItem("manual_review", "MISSING_PROVINCE")
		self.assertTrue(self._is_retryable(item, "CLOSED"))

	def test_retry_accepts_permanent_failure_once_lead_is_reopened(self):
		item = self._RetryItem("manual_review", "INVALID_CURRENT_OWNERSHIP")
		self.assertTrue(self._is_retryable(item, "PROCESSED"))

	def test_retry_accepts_routing_review_failure_without_reopening(self):
		item = self._RetryItem("manual_review", "NO_ELIGIBLE_RECIPIENT")
		self.assertTrue(self._is_retryable(item, "PROCESSED"))

	def test_retry_leaves_already_assigned_items_alone(self):
		item = self._RetryItem("assigned", None)
		self.assertFalse(self._is_retryable(item, "ASSIGNED"))
