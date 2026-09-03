"""Student 360 must complete before the Next Best Action stage is claimable.

These are isolated unit tests: the claim/settlement transactions themselves are
covered by the Bench suite, but the ordering guard is pure logic over the
sibling stage status and is verified here without a database.
"""

import unittest
from unittest.mock import MagicMock, patch

from crm.fcrm import intelligence_runs

_RUN_TYPE = intelligence_runs.RUN_TYPES["student"]


class TestNextBestActionStageDependency(unittest.TestCase):
	def _blocked(self, sibling_status):
		with patch(
			"crm.fcrm.intelligence_runs.frappe.db.get_value", return_value=sibling_status
		):
			return intelligence_runs._next_best_action_blocked_on_360(_RUN_TYPE, "RUN-1", 3)

	def test_deferred_while_sibling_is_queued(self):
		result = self._blocked("queued")
		self.assertEqual(result["deferred"], True)
		self.assertEqual(result["claimed"], False)
		self.assertEqual(result["blocked_on"], "student_360")
		self.assertEqual(result["stage_generation"], 3)

	def test_deferred_while_sibling_is_running(self):
		self.assertIsNotNone(self._blocked("running"))

	def test_released_when_sibling_completed(self):
		self.assertIsNone(self._blocked("completed"))

	def test_released_when_sibling_died_terminal_non_completed(self):
		self.assertIsNone(self._blocked("abstained"))
		self.assertIsNone(self._blocked("dead_lettered"))
		self.assertIsNone(self._blocked("failed"))

	def test_fail_closed_when_no_sibling_row(self):
		# Every student run materializes a student_360 stage; a missing sibling
		# means broken materialization and must never let the NBA claim through.
		result = self._blocked(None)
		self.assertIsNotNone(result)
		self.assertEqual(result["deferred"], True)
		self.assertEqual(result["status"], "missing")

	def test_claim_stage_defers_before_taking_a_lease(self):
		stage = MagicMock()
		stage.name = "STAGE-NBA"
		stage.status = "queued"
		stage.stage_generation = 0
		with patch("crm.fcrm.intelligence_runs._service_only"), patch(
			"crm.fcrm.intelligence_runs.frappe.get_doc", return_value=stage
		), patch("crm.fcrm.intelligence_runs.frappe.db.sql") as sql, patch(
			"crm.fcrm.intelligence_runs._next_best_action_blocked_on_360",
			return_value={"claimed": False, "deferred": True, "blocked_on": "student_360"},
		):
			result = intelligence_runs.claim_stage(
				run_type=_RUN_TYPE, run_id="RUN-1", stage_kind="next_best_action", stage_generation=0
			)
		self.assertEqual(result["deferred"], True)
		# The CAS UPDATE that acquires a lease must never run for a blocked stage.
		for call in sql.call_args_list:
			self.assertNotIn("SET status='running'", call.args[0])
