from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.assignment_workspace import (
	_actor_context,
	_clean_row,
	_expected_revision_map,
	_filter_rows,
	_inherited_zone_mapping,
	_normalize_filters,
	_paginate_overview_rows,
	_parse_string_list,
	_school_assignment_revision,
	_workload_status,
	get_overview,
	get_setup_readiness,
	get_setup_workspace,
)


class TestAssignmentWorkspaceContract(FrappeTestCase):
	def test_ceo_role_is_global_without_a_staff_record(self):
		previous_user = frappe.session.user
		frappe.set_user("ceo@example.com")
		try:
			with patch(
				"crm.api.assignment_workspace._get_policy_roles",
				return_value=["Administrator"],
			):
				context = _actor_context()
		finally:
			frappe.set_user(previous_user)

		self.assertEqual(context["profile"], "ceo")
		self.assertTrue(context["is_system_manager"])
		self.assertEqual(context["staff"], None)
		self.assertEqual(context["teams"], [])

	def test_director_role_is_global_without_a_staff_record(self):
		previous_user = frappe.session.user
		frappe.set_user("director@example.com")
		try:
			with patch(
				"crm.api.assignment_workspace._get_policy_roles",
				return_value=["Admissions Director"],
			):
				context = _actor_context()
		finally:
			frappe.set_user(previous_user)

		self.assertEqual(context["profile"], "admissions_director")
		self.assertFalse(context["is_system_manager"])
		self.assertEqual(context["staff"], None)
		self.assertEqual(context["teams"], [])

	def test_lead_sale_can_access_team_management_without_staff_record(self):
		previous_user = frappe.session.user
		frappe.set_user("leadsale@example.com")
		try:
			with (
				patch(
					"crm.api.assignment_workspace._get_policy_roles",
					return_value=["Lead Sale"],
				),
				patch.object(frappe.db, "get_value", return_value=None),
			):
				context = _actor_context(
					required_capabilities={"team.oversee"},
					allow_missing_staff=True,
				)
		finally:
			frappe.set_user(previous_user)

		self.assertEqual(context["profile"], "lead_sales")
		self.assertIsNone(context["staff"])
		self.assertEqual(context["teams"], [])

	def test_batch_payload_helpers_are_bounded_and_complete(self):
		self.assertEqual(
			_parse_string_list('["school-a", "school-a", "school-b"]', "schools"), ["school-a", "school-b"]
		)
		with self.assertRaises(frappe.ValidationError):
			_parse_string_list("[]", "schools")
		with self.assertRaises(frappe.ValidationError):
			_parse_string_list('{"school-a": "1"}', "schools")

	def test_batch_revision_map_requires_each_target(self):
		self.assertEqual(
			_expected_revision_map('{"school-a": 2, "school-b": "3"}', ["school-a", "school-b"]),
			{"school-a": "2", "school-b": "3"},
		)
		with self.assertRaises(frappe.ValidationError):
			_expected_revision_map('{"school-a": "1"}', ["school-a", "school-b"])

	def test_filter_contract_rejects_unknown_values(self):
		self.assertEqual(
			_normalize_filters({"status": "unassigned", "search": "Ben Nghe"}),
			{"status": "unassigned", "search": "Ben Nghe"},
		)
		with self.assertRaises(frappe.ValidationError):
			_normalize_filters({"status": "not-a-status"})
		with self.assertRaises(frappe.ValidationError):
			_normalize_filters({"unsafe_sql": "1"})

	def test_filter_keeps_matching_row_and_its_ancestors(self):
		rows = [
			{"id": "campus:1", "parent_id": None, "filter_values": {"campus": {"C1"}}, "status": "healthy"},
			{
				"id": "school:1",
				"parent_id": "campus:1",
				"filter_values": {"campus": {"C1"}, "school": {"S1"}},
				"status": "unassigned",
			},
			{
				"id": "school:2",
				"parent_id": "campus:1",
				"filter_values": {"campus": {"C1"}, "school": {"S2"}},
				"status": "healthy",
			},
		]
		result = _filter_rows(rows, {"school": "S1", "status": "unassigned"})
		self.assertEqual([row["id"] for row in result], ["campus:1", "school:1"])

	def test_filter_by_zone_keeps_all_schools_in_that_zone(self):
		rows = [
			{
				"id": "cluster:kh",
				"parent_id": None,
				"filter_values": {"province": {"KH"}},
			},
			{
				"id": "zone:kh",
				"parent_id": "cluster:kh",
				"filter_values": {"province": {"KH"}, "zone": {"ZONE-KH"}},
			},
			{
				"id": "school:kh-1",
				"parent_id": "zone:kh",
				"filter_values": {"province": {"KH"}, "zone": {"ZONE-KH"}},
			},
			{
				"id": "school:kh-2",
				"parent_id": "zone:kh",
				"filter_values": {"province": {"KH"}, "zone": {"ZONE-KH"}},
			},
			{
				"id": "school:hcm-1",
				"parent_id": "zone:hcm",
				"filter_values": {"province": {"HCM"}, "zone": {"ZONE-HCM"}},
			},
		]

		result = _filter_rows(rows, {"zone": "ZONE-KH"})
		self.assertEqual(
			[row["id"] for row in result], ["cluster:kh", "zone:kh", "school:kh-1", "school:kh-2"]
		)

	def test_workload_states_are_deterministic(self):
		self.assertEqual(_workload_status(0, None), "unconfigured")
		self.assertEqual(_workload_status(5, {"max_active_students": 5}), "over_capacity")
		self.assertEqual(_workload_status(9, {"max_active_students": 10}), "near_capacity")
		self.assertEqual(_workload_status(2, {"max_active_students": 5}), "healthy")

	def test_school_can_inherit_one_effective_zone_team_pool_mapping(self):
		teams = {"team-a": {"name": "team-a", "is_active": 1, "team_type": "Sales"}}
		zone_assignments = {"zone-a": [{"name": "map-a", "team": "team-a", "revision": 3}]}
		pools = {
			"team-a": [{"name": "pool-a", "campus": "campus-a"}],
		}

		self.assertEqual(
			_inherited_zone_mapping("zone-a", "campus-a", teams, zone_assignments, pools),
			{"team": "team-a", "pool": "pool-a", "assignment": "map-a", "revision": 3},
		)
		self.assertIsNone(_inherited_zone_mapping("zone-a", "campus-b", teams, zone_assignments, pools))
		self.assertIsNone(
			_inherited_zone_mapping(
				"zone-a",
				"campus-a",
				teams,
				{"zone-a": [*zone_assignments["zone-a"], {"name": "map-b", "team": "team-a"}]},
				pools,
			)
		)
		self.assertIsNone(
			_inherited_zone_mapping(
				"zone-a",
				"campus-a",
				teams,
				zone_assignments,
				{"team-a": [*pools["team-a"], {"name": "pool-b", "campus": "campus-a"}]},
			)
		)
		self.assertIsNone(
			_inherited_zone_mapping(
				"zone-a",
				"campus-a",
				{"team-a": {"name": "team-a", "is_active": 1, "team_type": "Marketing"}},
				zone_assignments,
				pools,
			)
		)

	def test_clean_row_keeps_expand_affordance_when_children_are_outside_page(self):
		children = {"cluster:1": ["zone:1"]}
		cleaned = _clean_row(
			{"id": "cluster:1", "label": "Cụm 1", "has_children": False, "filter_values": {}},
			children,
		)
		self.assertTrue(cleaned["has_children"])

	def test_overview_paginates_schools_without_hiding_team_topology(self):
		rows = [
			{"id": "cluster:1", "level": "cluster", "path": "cluster:1"},
			{"id": "zone:1", "level": "zone", "path": "cluster:1/zone:1"},
			{"id": "school:1", "level": "high_school", "path": "cluster:1/zone:1/school:1"},
			{"id": "team:1", "level": "team", "path": "cluster:1/zone:1/team:1"},
			{"id": "staff:1", "level": "staff", "path": "cluster:1/zone:1/team:1/staff:1"},
			{"id": "school:2", "level": "high_school", "path": "cluster:1/zone:1/school:2"},
		]

		first_page, next_cursor = _paginate_overview_rows(rows, 0, 1)
		self.assertEqual(
			[row["id"] for row in first_page], ["cluster:1", "zone:1", "team:1", "staff:1", "school:1"]
		)
		self.assertEqual(next_cursor, "1")

		second_page, next_cursor = _paginate_overview_rows(rows, int(next_cursor), 1)
		self.assertEqual([row["id"] for row in second_page], ["school:2"])
		self.assertIsNone(next_cursor)

	def test_school_revision_is_stable_for_same_active_mapping(self):
		rows = [
			{"name": "assignment-b", "modified": "2026-09-05 10:00:00", "staff": "staff-b", "team": "team-b"},
			{"name": "assignment-a", "modified": "2026-09-05 09:00:00", "staff": "staff-a", "team": "team-a"},
		]
		revision = _school_assignment_revision(rows)
		self.assertEqual(revision, _school_assignment_revision(list(reversed(rows))))
		self.assertNotEqual(
			revision,
			_school_assignment_revision(
				[
					*rows,
					{"name": "assignment-c", "modified": "2026-09-05 11:00:00"},
				]
			),
		)

	def test_administrator_receives_both_workspace_contracts(self):
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		try:
			overview = get_overview(limit=5)
			readiness = get_setup_readiness()
			self.assertIn(overview["contractStatus"], {"ready", "partial"})
			self.assertIn("summary", overview)
			self.assertIn("filter_schema", overview)
			self.assertIn("rows", overview)
			self.assertIn("summary", readiness)
			self.assertNotIn("Administrator", {row["user"] for row in readiness["rows"]})
			self.assertNotIn("platform_superuser", {row["role_state"] for row in readiness["rows"]})
		finally:
			frappe.set_user(previous_user)

	def test_setup_workspace_exposes_creation_references(self):
		previous_user = frappe.session.user
		frappe.set_user("Administrator")
		try:
			setup = get_setup_workspace()
			self.assertIn("clusters", setup)
			self.assertIn("pools", setup)
			self.assertIn("provinces", setup["options"])
			self.assertIn("clusters", setup["options"])
			self.assertIn("pools", setup["summary"])
		finally:
			frappe.set_user(previous_user)
