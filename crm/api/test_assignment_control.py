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
