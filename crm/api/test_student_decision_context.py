# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Tests for the additive score-evidence projection (`_score_projection`)
-- freshness must mirror the same (score_input_revision, policy_revision)
tuple ordering the CAS write layer
(`crm.api.scoring_write.append_score_if_current`) already uses."""

from unittest.mock import patch

from frappe.tests.utils import FrappeTestCase

from crm.api.student_decision_context import _score_projection


class TestScoreProjection(FrappeTestCase):
	def _policy(self, policy_revision=1, policy_hash="deadbeef"):
		return {"policy_revision": policy_revision, "policy_hash": policy_hash}

	def test_unknown_when_never_scored(self):
		row = {
			"latest_score": None,
			"score_input_revision": 3,
			"applied_score_input_revision": 0,
			"applied_policy_revision": 0,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=self._policy()):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "unknown")
		self.assertEqual(result["current_revision"], 3)
		self.assertIsNone(result["required_revision"])

	def test_current_when_applied_matches_latest_facts_and_policy(self):
		row = {
			"latest_score": 55.0,
			"score_input_revision": 5,
			"applied_score_input_revision": 5,
			"applied_policy_revision": 1,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=self._policy(policy_revision=1)):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "current")

	def test_pending_when_a_newer_fact_revision_exists(self):
		row = {
			"latest_score": 40.0,
			"score_input_revision": 7,
			"applied_score_input_revision": 5,
			"applied_policy_revision": 1,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=self._policy(policy_revision=1)):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "pending")

	def test_pending_when_policy_revision_advanced_past_applied(self):
		row = {
			"latest_score": 40.0,
			"score_input_revision": 5,
			"applied_score_input_revision": 5,
			"applied_policy_revision": 1,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=self._policy(policy_revision=2)):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "pending")

	def test_no_active_policy_defaults_to_zero_revision(self):
		row = {
			"latest_score": 40.0,
			"score_input_revision": 0,
			"applied_score_input_revision": 0,
			"applied_policy_revision": 0,
		}
		with patch("crm.api.student_decision_context.get_active_policy", return_value=None):
			result = _score_projection(row)

		self.assertEqual(result["freshness"], "current")
		self.assertEqual(result["policy_revision"], 0)
		self.assertEqual(result["policy_hash"], "")
