import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.assignment_workspace import (
	_clean_row,
	_expected_revision_map,
	_filter_rows,
	_normalize_filters,
	_parse_string_list,
	_school_assignment_revision,
	_workload_status,
	get_overview,
	get_setup_readiness,
)


class TestAssignmentWorkspaceContract(FrappeTestCase):
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

	def test_workload_states_are_deterministic(self):
		self.assertEqual(_workload_status(0, None), "unconfigured")
		self.assertEqual(_workload_status(5, {"max_active_students": 5}), "over_capacity")
		self.assertEqual(_workload_status(9, {"max_active_students": 10}), "near_capacity")
		self.assertEqual(_workload_status(2, {"max_active_students": 5}), "healthy")

	def test_clean_row_keeps_expand_affordance_when_children_are_outside_page(self):
		children = {"cluster:1": ["zone:1"]}
		cleaned = _clean_row(
			{"id": "cluster:1", "label": "Cụm 1", "has_children": False, "filter_values": {}},
			children,
		)
		self.assertTrue(cleaned["has_children"])

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
			administrator = next(row for row in readiness["rows"] if row["user"] == "Administrator")
			self.assertEqual(administrator["role_state"], "platform_superuser")
			self.assertEqual(administrator["status"], "healthy")
		finally:
			frappe.set_user(previous_user)
