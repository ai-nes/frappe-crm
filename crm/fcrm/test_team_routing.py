from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.fcrm import team_routing


class TestStaffCapacityConfiguredFlag(TestCase):
	def test_capacity_snapshot_marks_configured_by_default(self):
		self.assertEqual(
			team_routing._capacity_snapshot(10, 3),
			{"active": 3, "limit": 10, "remaining": 7, "configured": True},
		)

	def test_capacity_snapshot_can_mark_unconfigured(self):
		self.assertEqual(
			team_routing._capacity_snapshot(0, 3, configured=False),
			{"active": 3, "limit": None, "remaining": None, "configured": False},
		)

	def test_staff_capacity_is_unconfigured_when_no_period_exists(self):
		with (
			patch.object(team_routing.frappe.db, "get_value", return_value=None),
			patch.object(team_routing, "active_lead_count", return_value=2),
		):
			capacity = team_routing._staff_capacity("STAFF-1")
		self.assertFalse(capacity["configured"])
		self.assertIsNone(capacity["limit"])
		self.assertEqual(capacity["active"], 2)

	def test_staff_capacity_is_configured_when_an_approved_period_covers_now(self):
		with (
			patch.object(
				team_routing.frappe.db,
				"get_value",
				return_value=frappe._dict(max_active_students=5),
			),
			patch.object(team_routing, "active_lead_count", return_value=1),
		):
			capacity = team_routing._staff_capacity("STAFF-1")
		self.assertTrue(capacity["configured"])
		self.assertEqual(capacity["limit"], 5)


class TestActiveTeamRecipientsRequireConfiguredCapacity(TestCase):
	def test_staff_without_configured_capacity_is_excluded(self):
		pool = [
			{
				"staff": "STAFF-UNSET",
				"staffName": "Chưa thiết lập",
				"team": "TEAM-1",
				"function": "Sale",
				"capacity": {"active": 0, "limit": None, "remaining": None, "configured": False},
			},
			{
				"staff": "STAFF-OK",
				"staffName": "Đã thiết lập",
				"team": "TEAM-1",
				"function": "Sale",
				"capacity": {"active": 1, "limit": 5, "remaining": 4, "configured": True},
			},
		]
		with patch.object(team_routing, "_team_recipient_pool", return_value=pool):
			eligible = team_routing._active_team_recipients("TEAM-1")
		self.assertEqual([row["staff"] for row in eligible], ["STAFF-OK"])

	def test_staff_configured_but_over_limit_is_still_excluded(self):
		pool = [
			{
				"staff": "STAFF-FULL",
				"staffName": "Đã đầy",
				"team": "TEAM-1",
				"function": "Sale",
				"capacity": {"active": 5, "limit": 5, "remaining": 0, "configured": True},
			}
		]
		with patch.object(team_routing, "_team_recipient_pool", return_value=pool):
			eligible = team_routing._active_team_recipients("TEAM-1")
		self.assertEqual(eligible, [])
