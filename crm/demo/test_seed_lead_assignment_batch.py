"""Offline contract tests for the Lead assignment batch fixture."""

from __future__ import annotations

import unittest

from crm.demo import seed_lead_assignment_batch


class TestSeedLeadAssignmentBatchData(unittest.TestCase):
	def test_fixture_contains_ten_unique_student_scenarios(self):
		scenarios = seed_lead_assignment_batch.STUDENT_SCENARIOS

		self.assertEqual(len(scenarios), 10)
		self.assertEqual(len({row["key"] for row in scenarios}), 10)
		self.assertEqual(len({row["email"] for row in scenarios}), 10)
		self.assertTrue(all(row["email"].endswith("@example.test") for row in scenarios))

	def test_fixture_uses_a_draft_batch_for_the_dashboard_flow(self):
		self.assertEqual(
			seed_lead_assignment_batch.NAMESPACE,
			"crm-demo-lead-assignment-batch",
		)
		self.assertEqual(seed_lead_assignment_batch.BATCH_NAME, "Demo phân công 10 Lead")
		self.assertFalse(seed_lead_assignment_batch.SEED_SPEC.assign_students_to_account)
		self.assertTrue(seed_lead_assignment_batch.SEED_SPEC.is_team_lead)


if __name__ == "__main__":
	unittest.main()
