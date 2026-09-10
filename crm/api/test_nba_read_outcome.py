"""Outcome drill-down: ``CRM Action Outcome`` has no student/action/
recommendation column of its own, so the list filter and the ``get`` resolver
both walk execution -> task -> student, re-checking read permission at each
hop. These tests patch the ``frappe`` boundary rather than staging fixtures.
"""

import unittest
from unittest.mock import MagicMock, patch

from crm.api.nba_read import _execution_names_for_outcome_filters, get_action_outcome


class _FakeDoc:
	def __init__(self, values: dict):
		self._values = values
		self.check_permission = MagicMock()

	def get(self, key, default=None):
		return self._values.get(key, default)

	def as_dict(self):
		return dict(self._values)


class TestExecutionNamesForOutcomeFilters(unittest.TestCase):
	def test_no_filters_skips_the_join(self):
		self.assertIsNone(_execution_names_for_outcome_filters())

	def test_recommendation_only_filters_executions_directly(self):
		with patch("crm.api.nba_read.frappe.get_all", return_value=["EXEC-1"]) as get_all:
			result = _execution_names_for_outcome_filters(recommendation="REC-1")
		self.assertEqual(result, ["EXEC-1"])
		get_all.assert_called_once_with(
			"CRM Action Execution", filters={"recommendation": "REC-1"}, pluck="name"
		)

	def test_student_filter_joins_through_task_first(self):
		def side_effect(doctype, filters=None, pluck=None, **kwargs):
			if doctype == "CRM Action Item":
				self.assertEqual(filters, {"student": "STU-1"})
				return ["TASK-1", "TASK-2"]
			self.assertEqual(filters, {"task": ["in", ["TASK-1", "TASK-2"]]})
			return ["EXEC-1"]

		with patch("crm.api.nba_read.frappe.get_all", side_effect=side_effect):
			result = _execution_names_for_outcome_filters(student="STU-1")
		self.assertEqual(result, ["EXEC-1"])

	def test_student_with_no_matching_tasks_short_circuits_to_empty(self):
		with patch("crm.api.nba_read.frappe.get_all", return_value=[]) as get_all:
			result = _execution_names_for_outcome_filters(student="STU-NONE")
		self.assertEqual(result, [])
		get_all.assert_called_once()


class TestGetActionOutcome(unittest.TestCase):
	def test_drill_down_resolves_a_verified_outcome_ref_with_permission_rechecks(self):
		outcome_doc = _FakeDoc(
			{
				"name": "OUTCOME-1",
				"execution": "EXEC-1",
				"outcome_type": "action_execution",
				"outcome_value": "NOT_INTERESTED",
			}
		)
		execution_doc = _FakeDoc({"task": "TASK-1", "recommendation": "REC-1"})
		task_doc = _FakeDoc({"student": "STU-1"})

		def get_doc(doctype, name):
			return {
				("CRM Action Outcome", "OUTCOME-1"): outcome_doc,
				("CRM Action Execution", "EXEC-1"): execution_doc,
				("CRM Action Item", "TASK-1"): task_doc,
			}[(doctype, name)]

		with patch("crm.api.nba_read.frappe.get_doc", side_effect=get_doc), patch(
			"crm.api.nba_read.frappe.local"
		) as fake_local:
			fake_local.site = "crm.localhost"
			row = get_action_outcome("OUTCOME-1")

		outcome_doc.check_permission.assert_called_once_with("read")
		execution_doc.check_permission.assert_called_once_with("read")
		task_doc.check_permission.assert_called_once_with("read")
		ref = row["outcome_ref"]
		self.assertEqual(ref["outcome_id"], "OUTCOME-1")
		self.assertEqual(ref["decision_id"], "REC-1")
		self.assertEqual(ref["subject"]["subject_id"], "STU-1")
		self.assertTrue(ref["verified"])

	def test_no_linked_execution_returns_the_bare_row(self):
		outcome_doc = _FakeDoc({"name": "OUTCOME-2", "execution": None})
		with patch("crm.api.nba_read.frappe.get_doc", return_value=outcome_doc):
			row = get_action_outcome("OUTCOME-2")
		self.assertNotIn("outcome_ref", row)
