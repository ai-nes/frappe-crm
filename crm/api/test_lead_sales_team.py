"""Focused contracts for the Lead Sale sales-team API projection."""

from datetime import date
from unittest.mock import patch
from zoneinfo import ZoneInfo

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import lead_sales_team


class TestLeadSalesTeam(FrappeTestCase):
	def test_name_sort_defaults_to_ascending(self):
		query = lead_sales_team._parse_query("all", "", 1, 50, "name", None)
		self.assertEqual(query["order"], "asc")

	def test_capacity_zero_returns_null_load_rate_and_overdue_support(self):
		members = lead_sales_team._build_members(
			[
				{
					"id": "STAFF-1",
					"displayName": "Nguyễn Minh Anh",
					"email": "minhanh@example.test",
					"availability": "active",
					"teams": {"TEAM-1"},
				}
			],
			[
				{
					"name": "STUDENT-1",
					"student_name": "Học sinh 1",
					"owner_staff": "STAFF-1",
					"province": "P1",
					"major": "M1",
				}
			],
			[
				{
					"id": "STUDENT-1",
					"owner_staff": "STAFF-1",
					"consulted_at": "2026-09-05 08:00:00",
					"admitted_at": "2026-09-05 08:30:00",
				}
			],
			[
				{
					"student": "STUDENT-1",
					"interaction_datetime": "2026-09-05 08:00:00",
				}
			],
			[{"student_id": "STUDENT-1", "is_overdue": True, "status": "Todo"}],
			{},
			{"provinces": {"P1": "Cần Thơ"}, "majors": {"M1": "Công nghệ thông tin"}},
			date(2026, 9, 5),
			ZoneInfo("Asia/Ho_Chi_Minh"),
		)

		self.assertEqual(len(members), 1)
		self.assertIsNone(members[0]["loadRate"])
		self.assertEqual(members[0]["overdue"], 1)
		self.assertEqual(members[0]["health"], "support")
		self.assertEqual(members[0]["regions"], ["Cần Thơ"])

	def test_support_sort_is_stable(self):
		rows = [
			{"id": "STAFF-2", "displayName": "Trần B", "health": "good", "overdue": 0, "loadRate": 90},
			{"id": "STAFF-1", "displayName": "Lê A", "health": "support", "overdue": 2, "loadRate": 50},
			{"id": "STAFF-3", "displayName": "Phạm C", "health": "support", "overdue": 1, "loadRate": 95},
		]
		self.assertEqual(
			[row["id"] for row in lead_sales_team._sort_members(rows, "support", "desc")],
			["STAFF-1", "STAFF-3", "STAFF-2"],
		)

	@patch.object(lead_sales_team.frappe.db, "table_exists", return_value=True)
	@patch.object(
		lead_sales_team.frappe,
		"get_all",
		return_value=[{"parent": "STAFF-1", "team": "TEAM-1", "function": "Sale"}],
	)
	def test_team_membership_projection_uses_child_table_read(self, get_all, _table_exists):
		rows = lead_sales_team._read_all(
			"CRM Team Membership",
			filters={"parent": "STAFF-1", "parenttype": "CRM Staff"},
			fields=["parent", "team", "function"],
			warnings=[],
			warning_key="team",
		)

		self.assertEqual(rows[0]["team"], "TEAM-1")
		get_all.assert_called_once()

	@patch.object(
		lead_sales_team.lead_sale_api, "_require_access", return_value={"user": "lead@example.test"}
	)
	def test_detail_requires_member_id(self, _require_access):
		with self.assertRaises(frappe.ValidationError):
			lead_sales_team.get_sales_team_member_detail("")
