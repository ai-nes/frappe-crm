"""Per-dimension outcome resolution: each dimension is resolved against only
the outcome history that can affect it, keyset-paginated on
``(completed_at, name)``, plus the immutable ``CRM Action Outcome`` lineage
lookup for whichever row resolves it.

The resolver reads completed ``CRM Action Item`` rows through
``crm.api.nba_evaluation.frappe.db.sql`` and the lineage lookup through
``crm.api.nba_evaluation.frappe.get_all``; these tests patch both boundaries
with synthetic rows rather than staging a deep history in the database.
"""

import unittest
from unittest.mock import patch

from crm.api.nba_evaluation import _decision_effect_signals


def _row(action, outcome, *, name=None, completed_at="2026-09-01 09:00:00", revisit_at=None):
	return {
		"name": name or f"TASK-{action}-{outcome}-{completed_at}",
		"action": action,
		"action_type": action,
		"outcome_code": outcome,
		"revisit_at": revisit_at,
		"completed_at": completed_at,
	}


_NOOP = _row("CREATE_TASK", "COMPLETED", name="TASK-NOOP")  # INTERNAL: allowed, no decision effect


def _fake_sql_over(rows: list[dict]):
	"""Simulate the keyset-paginated ``frappe.db.sql`` newest-first scan over
	``rows`` by re-deriving ``codes``/``after`` from the bound SQL parameters --
	close enough to the real query (sorted ``completed_at desc, name desc``,
	strictly-less-than cursor) to exercise the resolver's paging loop without a
	live database.
	"""

	def sql(query, values, as_dict=True):
		limit = values["limit"]
		codes = set(values["codes"]) if "codes" in values else None
		matching = [row for row in rows if codes is None or row["outcome_code"] in codes]
		matching.sort(key=lambda row: (row.get("completed_at") or "", row["name"]), reverse=True)
		if "after_name" in values:
			after_key = (values.get("after_at") or "", values["after_name"])
			matching = [row for row in matching if (row.get("completed_at") or "", row["name"]) < after_key]
		return matching[:limit]

	return sql


class TestDecisionEffectFold(unittest.TestCase):
	def _fold(self, rows, *, executions=(), outcomes=()):
		def get_all(doctype, filters=None, fields=None, **kwargs):
			if doctype == "CRM Action Execution":
				return list(executions)
			if doctype == "CRM Action Outcome":
				return list(outcomes)
			raise AssertionError(f"unexpected doctype queried: {doctype}")

		with patch("crm.api.nba_evaluation.frappe.db.sql", side_effect=_fake_sql_over(list(rows))), patch(
			"crm.api.nba_evaluation.frappe.get_all", side_effect=get_all
		):
			return _decision_effect_signals("STU-1")

	def test_latest_signal_survives_far_beyond_the_old_fifty_row_window(self):
		# A closing signal followed by 120 unrelated administrative actions: a
		# ``latest`` dimension must still see it -- the per-dimension query is
		# scoped to interest-affecting codes, not a shared history window.
		rows = [_NOOP] * 120 + [
			_row("CALL", "NOT_INTERESTED", name="TASK-CLOSE", completed_at="2026-01-02 08:00:00")
		]
		result = self._fold(rows)
		self.assertEqual(result["interest_disposition"]["value"], "not_interested")
		self.assertEqual(result["coverage"]["interest_disposition"], "known")

	def test_closing_signal_beyond_the_query_budget_is_marked_incomplete_not_absent(self):
		# 501 rows all carrying an interest-affecting code but every one
		# mismatched to its category (so none actually resolves the
		# dimension) exhausts the per-dimension budget before a real answer.
		rows = [
			_row("REASSIGN_ADVISOR", "NOT_INTERESTED", name=f"TASK-{i}", completed_at=f"2026-09-{(i % 27) + 1:02d} 09:00:00")
			for i in range(501)
		]
		result = self._fold(rows)
		self.assertNotIn("interest_disposition", result)
		self.assertEqual(result["coverage"]["interest_disposition"], "incomplete")

	def test_folded_effect_carries_source_outcome_and_occurred_at(self):
		result = self._fold(
			[_row("CALL", "NOT_INTERESTED", name="TASK-A", completed_at="2026-09-04 10:30:00")]
		)
		effect = result["interest_disposition"]
		self.assertEqual(effect["source_outcome"], {"outcome_code": "NOT_INTERESTED", "action": "CALL"})
		self.assertEqual(effect["occurred_at"], "2026-09-04 10:30:00")

	def test_no_linked_execution_falls_back_to_legacy_task_provenance(self):
		result = self._fold(
			[_row("CALL", "NOT_INTERESTED", name="TASK-LEGACY", completed_at="2026-09-04 10:30:00")]
		)
		effect = result["interest_disposition"]
		self.assertEqual(effect["source_kind"], "legacy_task")
		self.assertEqual(effect["task"], "TASK-LEGACY")
		self.assertNotIn("outcome_ref", effect)

	def test_linked_immutable_outcome_yields_a_verified_outcome_ref(self):
		result = self._fold(
			[_row("CALL", "NOT_INTERESTED", name="TASK-VERIFIED", completed_at="2026-09-04 10:30:00")],
			executions=[{"name": "EXEC-1", "task": "TASK-VERIFIED", "recommendation": "REC-1"}],
			outcomes=[
				{
					"name": "OUTCOME-1",
					"execution": "EXEC-1",
					"outcome_value": "NOT_INTERESTED",
					"captured_at": "2026-09-04 10:31:00",
				}
			],
		)
		effect = result["interest_disposition"]
		self.assertEqual(effect["source_kind"], "verified_outcome")
		self.assertNotIn("task", effect)
		ref = effect["outcome_ref"]
		self.assertEqual(ref["outcome_id"], "OUTCOME-1")
		self.assertEqual(ref["kind"], "verified_outcome")
		self.assertTrue(ref["verified"])
		self.assertEqual(ref["decision_id"], "REC-1")
		self.assertEqual(ref["subject"]["subject_id"], "STU-1")

	def test_two_completions_with_the_same_outcome_code_keep_distinct_refs(self):
		rows = [
			_row("CALL", "NO_RESPONSE", name="TASK-1", completed_at="2026-09-05 09:00:00"),
			_row("CALL", "NO_RESPONSE", name="TASK-2", completed_at="2026-09-03 09:00:00"),
		]
		executions = [
			{"name": "EXEC-1", "task": "TASK-1", "recommendation": "REC-1"},
			{"name": "EXEC-2", "task": "TASK-2", "recommendation": "REC-2"},
		]
		outcomes = [
			{"name": "OUTCOME-1", "execution": "EXEC-1", "outcome_value": "NO_RESPONSE", "captured_at": "x"},
			{"name": "OUTCOME-2", "execution": "EXEC-2", "outcome_value": "NO_RESPONSE", "captured_at": "y"},
		]
		with patch(
			"crm.api.nba_evaluation.frappe.get_all",
			side_effect=lambda doctype, filters=None, fields=None, **kwargs: {
				"CRM Action Execution": executions,
				"CRM Action Outcome": outcomes,
			}[doctype],
		):
			from crm.api.nba_evaluation import _immutable_outcome_refs_for_tasks

			refs = _immutable_outcome_refs_for_tasks(["TASK-1", "TASK-2"])
		self.assertNotEqual(refs["TASK-1"]["outcome_name"], refs["TASK-2"]["outcome_name"])

	def test_contact_streak_reports_the_most_recent_failure_time(self):
		rows = [
			_row("CALL", "NO_RESPONSE", name="TASK-1", completed_at="2026-09-05 09:00:00"),
			_row("CALL", "NO_RESPONSE", name="TASK-2", completed_at="2026-09-03 09:00:00"),
		]
		signal = self._fold(rows)["contact_attempt_signal"]
		self.assertEqual(signal["consecutive_failures"], 2)
		self.assertEqual(signal["occurred_at"], "2026-09-05 09:00:00")

	def test_follow_up_still_resets_when_the_newest_action_does_not_touch_it(self):
		rows = [
			_row("CALL", "NO_RESPONSE", name="TASK-1", completed_at="2026-09-05 09:00:00"),
			_row(
				"CALL",
				"CALL_BACK_LATER",
				name="TASK-2",
				completed_at="2026-09-01 09:00:00",
				revisit_at="2026-09-10 09:00:00",
			),
		]
		self.assertNotIn("follow_up", self._fold(rows))

	def test_decision_status_not_ready_is_cleared_by_a_more_recent_reopen(self):
		rows = [
			_row("CALL", "INTEREST_CONFIRMED", name="TASK-REOPEN", completed_at="2026-09-06 09:00:00"),
			_row("REENGAGE_LEAD", "NOT_READY", name="TASK-NOTREADY", completed_at="2026-09-01 09:00:00"),
		]
		result = self._fold(rows)
		self.assertNotIn("decision_status", result)
		self.assertEqual(result["coverage"]["decision_status"], "known")

	def test_decision_status_not_ready_persists_without_a_reopen(self):
		rows = [
			_row("REENGAGE_LEAD", "NOT_READY", name="TASK-NOTREADY", completed_at="2026-09-01 09:00:00"),
		]
		result = self._fold(rows)
		self.assertEqual(result["decision_status"]["value"], "not_ready")

	def test_no_matching_history_at_all_reports_known_absence_not_incomplete(self):
		result = self._fold([_NOOP])
		self.assertNotIn("interest_disposition", result)
		self.assertEqual(result["coverage"]["interest_disposition"], "known")
