from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.api import assignment_control


class TestUserCapacityEndpoints(TestCase):
	def test_list_user_capacity_keys_by_user_and_skips_staff_without_user(self):
		staff_rows = [
			frappe._dict(name="STAFF-1", user="sale1@example.com"),
			frappe._dict(name="STAFF-2", user="sale2@example.com"),
			frappe._dict(name="STAFF-3", user=None),
		]
		with (
			patch.object(assignment_control, "_require_control_access"),
			patch.object(assignment_control.frappe, "get_all", return_value=staff_rows) as get_all,
			patch.object(
				assignment_control,
				"_capacity_by_staff",
				return_value={"STAFF-1": {"max_active_students": 10}},
			),
			patch.object(
				assignment_control,
				"active_lead_count_by_staff",
				return_value={"STAFF-1": 3, "STAFF-2": 2},
			) as active_counts,
		):
			result = assignment_control.list_user_capacity()
		get_all.assert_called_once_with(
			"CRM Staff", filters={"is_active": 1}, fields=["name", "user"]
		)
		active_counts.assert_called_once_with(["STAFF-1", "STAFF-2"])
		self.assertEqual(
			result,
			{
				"sale1@example.com": {"active": 3, "limit": 10, "remaining": 7, "configured": True},
				# STAFF-2 has never been given a capacity period: the snapshot must
				# say so explicitly instead of looking identical to "unlimited".
				"sale2@example.com": {"active": 2, "limit": None, "remaining": None, "configured": False},
			},
		)

	def test_list_user_capacity_returns_empty_when_no_staffed_users_exist(self):
		with (
			patch.object(assignment_control, "_require_control_access"),
			patch.object(assignment_control.frappe, "get_all", return_value=[]),
			patch.object(assignment_control, "active_lead_count_by_staff") as active_counts,
		):
			result = assignment_control.list_user_capacity()
		active_counts.assert_not_called()
		self.assertEqual(result, {})

	def test_upsert_user_capacity_resolves_staff_from_user(self):
		with (
			patch.object(assignment_control, "_require_control_access"),
			patch.object(assignment_control.frappe.db, "get_value", return_value="STAFF-1") as get_value,
			patch.object(assignment_control, "upsert_staff_capacity", return_value={"ok": True}) as upsert,
		):
			result = assignment_control.upsert_user_capacity(
				user="sale1@example.com",
				max_active_students=8,
				reason="Cập nhật từ trang Quản lý người dùng",
			)
		get_value.assert_called_once_with(
			"CRM Staff", {"user": "sale1@example.com", "is_active": 1}, "name"
		)
		upsert.assert_called_once_with(
			staff="STAFF-1",
			max_active_students=8,
			reason="Cập nhật từ trang Quản lý người dùng",
		)
		self.assertEqual(result, {"ok": True})

	def test_upsert_user_capacity_raises_clear_error_when_user_has_no_staff_record(self):
		with (
			patch.object(assignment_control, "_require_control_access"),
			patch.object(assignment_control.frappe.db, "get_value", return_value=None),
		):
			with self.assertRaises(frappe.ValidationError):
				assignment_control.upsert_user_capacity(
					user="nostaff@example.com",
					max_active_students=5,
					reason="Thiết lập ban đầu",
				)


class TestLeadRoutingPolicyAccess(TestCase):
	def test_lead_sale_can_manage_lead_routing_policy(self):
		context = {"capabilities": ["student.routing.operate"]}
		with patch.object(assignment_control, "_actor_context", return_value=context):
			self.assertIs(assignment_control._require_lead_routing_policy_access(), context)

	def test_users_without_routing_operation_cannot_manage_lead_routing_policy(self):
		context = {"capabilities": ["student.routing.read"]}
		with patch.object(assignment_control, "_actor_context", return_value=context):
			with self.assertRaises(frappe.PermissionError):
				assignment_control._require_lead_routing_policy_access()

	def test_system_manager_can_manage_lead_routing_policy(self):
		context = {"capabilities": ["system.configure"]}
		with patch.object(assignment_control, "_actor_context", return_value=context):
			self.assertIs(assignment_control._require_lead_routing_policy_access(), context)


class TestLeadAssignmentWorkflowEndpoints(TestCase):
	def test_routing_reader_can_load_workflow_without_manage_capability(self):
		context = {"capabilities": ["student.routing.read"]}
		with (
			patch.object(assignment_control, "_actor_context", return_value=context),
			patch.object(assignment_control, "_stored_control", return_value={}),
		):
			result = assignment_control.get_lead_assignment_workflow_config()

		self.assertFalse(result["canManage"])
		self.assertEqual(result["config"]["stored"]["input"]["maxLeadsPerRun"], 1000)

	def test_lead_sale_can_update_one_workflow_step_with_revision_and_reason(self):
		context = {"capabilities": ["student.routing.operate"]}
		control = {
			"lead_assignment_workflow_config": "{}",
			"lead_workflow_revision": 2,
			"revision": 0,
		}
		doc = type("Control", (), {})()
		doc.save = lambda **_kwargs: None
		with (
			patch.object(assignment_control, "_require_lead_routing_policy_access", return_value=context),
			patch.object(assignment_control, "_actor_context", return_value=context),
			patch.object(assignment_control, "_stored_control", return_value=control),
			patch.object(assignment_control.frappe, "get_single", return_value=doc),
			patch.object(
				assignment_control,
				"_workflow_snapshot_response",
				return_value={"config": {"revision": 3}},
			),
		):
			result = assignment_control.update_lead_assignment_workflow_step(
				"input",
				{"enabled": False, "scheduledMinAgeMinutes": 12, "maxLeadsPerRun": 20},
				"Giảm tải job nền",
				expected_revision=2,
			)

		self.assertEqual(result, {"config": {"revision": 3}})
		self.assertEqual(doc.lead_workflow_revision, 3)
		self.assertEqual(doc.lead_assignment_workflow_config["input"]["maxLeadsPerRun"], 20)
		self.assertEqual(doc.lead_workflow_last_change_reason, "Giảm tải job nền")

	def test_workflow_update_rejects_stale_revision(self):
		context = {"capabilities": ["student.routing.operate"]}
		with (
			patch.object(assignment_control, "_require_lead_routing_policy_access", return_value=context),
			patch.object(
				assignment_control,
				"_stored_control",
				return_value={"lead_workflow_revision": 4},
			),
		):
			with self.assertRaises(frappe.ValidationError) as error:
				assignment_control.update_lead_assignment_workflow_step(
					"review", {"maxRetries": 2}, "Điều chỉnh retry", expected_revision=3
				)

		self.assertEqual(error.exception.code, "WORKFLOW_REVISION_CONFLICT")
