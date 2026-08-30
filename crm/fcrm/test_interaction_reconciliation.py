from __future__ import annotations

import unittest

from crm.fcrm.interaction_reconciliation import _plan_backfill


class TestInteractionReconciliation(unittest.TestCase):
	def test_plans_only_unambiguous_source_identities(self):
		eligible, conflicts = _plan_backfill(
			[
				{"name": "INT-1", "source_namespace": "chatwoot", "source_record_id": "m-1"},
				{"name": "INT-2", "source_namespace": "chatwoot", "source_record_id": "m-2"},
				{"name": "INT-3", "source_namespace": "chatwoot", "source_record_id": "m-1"},
				{"name": "INT-4", "source_namespace": "", "source_record_id": "m-4"},
			],
			{"chatwoot:m-2": 1},
		)

		self.assertEqual(eligible, [])
		self.assertCountEqual(
			[conflict["reason"] for conflict in conflicts],
			["duplicate_candidate", "external_id_exists", "duplicate_candidate", "missing_source_identity"],
		)

	def test_dry_run_plan_keeps_valid_identity(self):
		eligible, conflicts = _plan_backfill(
			[{"name": "INT-1", "source_namespace": "chatwoot", "source_record_id": "m-1"}],
			{},
		)

		self.assertEqual(eligible, [{"name": "INT-1", "external_id": "chatwoot:m-1"}])
		self.assertEqual(conflicts, [])
