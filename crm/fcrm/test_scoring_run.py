"""Focused tests for Frappe-local scoring orchestration safeguards."""

from unittest import TestCase
from unittest.mock import patch

from crm.fcrm.scoring_run import score_active_cohort


class TestScoringRun(TestCase):
	def test_active_cohort_paging_queues_every_student(self):
		with (
			patch(
				"crm.fcrm.scoring_run.frappe.get_all",
				side_effect=[["ENROLLED"], ["STU-1", "STU-2"], ["STU-3"]],
			) as get_all,
			patch("crm.fcrm.scoring_run.enqueue_score_student") as enqueue,
		):
			result = score_active_cohort(limit=2)

		self.assertEqual(result, {"queued": 3, "closed_statuses": 1})
		self.assertEqual([call.args[0] for call in enqueue.call_args_list], ["STU-1", "STU-2", "STU-3"])
		self.assertEqual(get_all.call_count, 3)
