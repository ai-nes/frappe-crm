from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api import lead_sale


class TestStudentAssignmentContract(FrappeTestCase):
	def test_summary_counts_are_snapshot_wide_and_mutually_exclusive(self):
		items = [
			{"status": "assigned", "method": "automatic"},
			{"status": "no_match", "method": "automatic"},
			{"status": "missing_data", "method": "automatic"},
			{"status": "error", "method": "automatic"},
		]

		summary = lead_sale._assignment_summary(items)

		self.assertEqual(summary["received"], 4)
		self.assertEqual(summary["assigned"], 1)
		self.assertEqual(summary["pending"], 3)
		self.assertEqual(sum(summary["byStatus"].values()), summary["received"])

	def test_filter_and_search_contract_keep_review_alias_permission_scoped(self):
		assigned = {"studentId": "HS-1", "status": "assigned", "owner": {"id": "STAFF-1"}}
		missing = {"studentId": "HS-2", "status": "missing_data", "owner": None}

		self.assertTrue(lead_sale._assignment_filter_matches(assigned, "assigned"))
		self.assertFalse(lead_sale._assignment_filter_matches(assigned, "review"))
		self.assertTrue(lead_sale._assignment_filter_matches(missing, "review"))
		self.assertTrue(
			lead_sale._assignment_matches({**missing, "name": "Nguyễn Minh An", "school": "THPT A"}, "nguyen")
		)
		self.assertFalse(
			lead_sale._assignment_matches({**missing, "name": "Trần Minh An", "school": "THPT A"}, "nguyen")
		)

	def test_sort_uses_student_id_as_stable_tie_breaker(self):
		left = {"studentId": "HS-002", "name": "An", "receivedAt": "2026-09-05T09:00:00+07:00"}
		right = {"studentId": "HS-001", "name": "An", "receivedAt": "2026-09-05T09:00:00+07:00"}

		self.assertGreater(lead_sale._assignment_compare(left, right, "receivedAt", "desc"), 0)
		self.assertGreater(lead_sale._assignment_compare(left, right, "receivedAt", "asc"), 0)

	def test_workspace_uses_scoped_student_query_and_selected_admission_year(self):
		scope = {"team_ids": ["TEAM-1"], "staff_ids": ["STAFF-1"]}
		with (
			patch.object(frappe.db, "table_exists", return_value=True),
			patch.object(frappe, "get_list", return_value=[]),
		):
			rows = lead_sale._assignment_load_students(scope, "2026", [])

		self.assertEqual(rows, [])
