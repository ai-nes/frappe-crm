from unittest import TestCase
from unittest.mock import patch

import frappe

from crm.fcrm import team_routing


class TestManualLeadRecipients(TestCase):
	def test_all_provinces_include_active_groups_and_specific_province_stays_scoped(self):
		teams = [
			frappe._dict(name="TEAM-1", group="GROUP-1"),
			frappe._dict(name="TEAM-2", group="GROUP-2"),
			frappe._dict(name="TEAM-INACTIVE-GROUP", group="GROUP-INACTIVE"),
		]
		groups = {
			"GROUP-1": frappe._dict(is_active=1, province="PROVINCE-1", group_name="Group 1"),
			"GROUP-2": frappe._dict(is_active=1, province="PROVINCE-2", group_name="Group 2"),
			"GROUP-INACTIVE": frappe._dict(is_active=0, province="PROVINCE-3"),
		}
		with (
			patch.object(team_routing.frappe, "get_all", return_value=teams) as query,
			patch.object(
				team_routing.frappe.db, "get_value", side_effect=lambda doctype, name, *a, **kw: groups[name]
			),
		):
			self.assertEqual(
				[row["name"] for row in team_routing._active_teams_for_province(None)], ["TEAM-1", "TEAM-2"]
			)
			self.assertEqual(
				[row["name"] for row in team_routing._active_teams_for_province("PROVINCE-1")], ["TEAM-1"]
			)
			self.assertEqual(query.call_args.kwargs["filters"], {"is_active": 1, "team_type": "Sales"})

	def test_missing_province_lists_sales_and_ctv_only_when_global_fallback_enabled(self):
		teams = [
			{"name": "TEAM-1", "team_name": "Team 1", "campus": "CAMPUS-1"},
			{"name": "TEAM-2", "team_name": "Team 2", "campus": "CAMPUS-2"},
		]

		def recipients(team_id, at):
			return [
				{
					"staff": team_id,
					"staffName": team_id,
					"team": team_id,
					"function": "Sale" if team_id == "TEAM-1" else "CTV Sale",
					"capacity": {"active": 0},
				}
			]

		with (
			patch.object(team_routing, "_active_teams_for_province", return_value=teams) as scope,
			patch.object(team_routing, "team_routing_readiness", return_value={"status": "ready"}),
			patch.object(team_routing, "_active_team_recipients", side_effect=recipients),
			patch.object(team_routing, "list_team_lead_recipients", return_value=[]),
		):
			self.assertEqual(team_routing.list_province_recipients(""), [])
			scope.assert_not_called()
			rows = team_routing.list_province_recipients("", include_leads=True, allow_all_provinces=True)
			self.assertEqual([row["function"] for row in rows], ["Sale", "CTV Sale"])
			scope.assert_called_once_with(None, campus=None)

	def test_designated_leads_are_active_enabled_and_deduplicated(self):
		def get_value(doctype, name, fields, **kwargs):
			if doctype == "CRM Team":
				return frappe._dict(team_lead_staff="TEAM-LEAD", group="GROUP-1")
			if doctype == "CRM Team Group":
				return "GROUP-LEAD"
			if doctype == "CRM Staff":
				return frappe._dict(name=name, full_name=name, user=name, is_active=1)
			if doctype == "User":
				return 1

		with (
			patch.object(team_routing.frappe.db, "get_value", side_effect=get_value),
			patch.object(team_routing, "active_lead_count", return_value=0),
		):
			rows = team_routing.list_team_lead_recipients("TEAM-1")
		self.assertEqual(
			[(r["staff"], r["function"]) for r in rows],
			[
				("GROUP-LEAD", "Lead Group"),
				("TEAM-LEAD", "Lead Team"),
			],
		)
		self.assertTrue(all(not r["capacity"]["configured"] for r in rows))

		for active, enabled in ((0, 1), (1, 0)):

			def disabled_value(doctype, name, fields, **kwargs):
				if doctype == "CRM Staff":
					return frappe._dict(name=name, full_name=name, user=name, is_active=active)
				if doctype == "User":
					return enabled
				return get_value(doctype, name, fields, **kwargs)

			with patch.object(team_routing.frappe.db, "get_value", side_effect=disabled_value):
				self.assertEqual(team_routing.list_team_lead_recipients("TEAM-1"), [])

		def same_lead(doctype, name, fields, **kwargs):
			if doctype == "CRM Team Group":
				return "TEAM-LEAD"
			return get_value(doctype, name, fields, **kwargs)

		with (
			patch.object(team_routing.frappe.db, "get_value", side_effect=same_lead),
			patch.object(team_routing, "active_lead_count", return_value=0),
		):
			self.assertEqual(len(team_routing.list_team_lead_recipients("TEAM-1")), 1)

	def test_manual_list_includes_leads_without_sales_and_keeps_automatic_selection_separate(self):
		team = {"name": "TEAM-1", "team_name": "Team 1", "campus": "OTHER-CAMPUS"}
		leader = {
			"staff": "LEAD-1",
			"staffName": "Leader",
			"function": "Lead Team",
			"capacity": {"active": 2},
			"team": "TEAM-1",
		}
		with (
			patch.object(team_routing, "_active_teams_for_province", return_value=[team]) as teams,
			patch.object(
				team_routing,
				"team_routing_readiness",
				return_value={
					"status": "not_ready",
					"reasonCode": "no_recipients",
				},
			),
			patch.object(team_routing, "list_team_lead_recipients", return_value=[leader]),
		):
			self.assertEqual(team_routing.list_province_recipients("PROVINCE-1"), [])
			rows = team_routing.list_province_recipients("PROVINCE-1", include_leads=True)
			self.assertEqual([r["staff"] for r in rows], ["LEAD-1"])
			teams.assert_called_with("PROVINCE-1", campus=None)


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
