# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Coverage for the WAIT re-evaluation boundary and its coalesced dispatch.

``commit_nba_evaluation_result`` now persists ``revisit_at`` and
``reevaluation_trigger`` from a WAIT disposition, and the hourly
``reconcile_due_reevaluations`` scheduler fires exactly one fresh automatic
evaluation per student for every due WAIT boundary -- the per-identity
single-active-run invariant collapses a burst of due boundaries into one run.
"""

import unittest
from unittest.mock import patch

try:
	import frappe
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - pure environment without a bench
	FrappeTestCase = None


if FrappeTestCase is not None:
	from frappe.utils import add_to_date, now_datetime

	from crm.fcrm import nba_evaluations

	class TestNbaWaitReevaluation(FrappeTestCase):
		@classmethod
		def setUpClass(cls):
			if not getattr(frappe, "db", None):
				raise unittest.SkipTest("re-evaluation tests require a bench site (use bench run-tests)")
			super().setUpClass()
			cls._conf_backup = {
				key: frappe.conf.get(key)
				for key in (
					"crm_nba_evaluation_runtime_enabled",
					"crm_agents_service_user",
					"crm_nba_manual_requests_per_actor_target",
					"crm_agents_outbox_enabled",
				)
			}
			frappe.conf["crm_nba_evaluation_runtime_enabled"] = 1
			frappe.conf["crm_agents_service_user"] = "Administrator"
			frappe.conf["crm_nba_manual_requests_per_actor_target"] = 500
			frappe.conf["crm_agents_outbox_enabled"] = 1
			student = frappe.get_all("CRM Student", pluck="name", limit_page_length=1)
			if not student:
				raise unittest.SkipTest("no seeded CRM Student on this site")
			cls.student = student[0]

		@classmethod
		def tearDownClass(cls):
			for key, value in cls._conf_backup.items():
				if value is None:
					frappe.conf.pop(key, None)
				else:
					frappe.conf[key] = value
			super().tearDownClass()

		def setUp(self):
			self._reset_rows()
			self._enqueue = frappe.enqueue
			frappe.enqueue = lambda *a, **k: None

		def tearDown(self):
			frappe.enqueue = self._enqueue
			self._reset_rows()

		def _reset_rows(self):
			frappe.db.delete("CRM Recommendation", {"target_id": self.student})
			frappe.db.delete("CRM NBA Evaluation", {"student": self.student})
			frappe.db.delete("CRM Agent Event", {"aggregate_doctype": "CRM NBA Evaluation"})
			frappe.db.commit()

		def _completed_wait(self, *, revisit_at, trigger=None):
			"""Insert a settled WAIT evaluation directly (controller-level scenario)."""
			doc = frappe.get_doc(
				{
					"doctype": "CRM NBA Evaluation",
					"student": self.student,
					"trigger": "automatic",
					"status": "completed",
					"disposition": "WAIT",
					"engine_revision": "nba-engine-test",
					"evaluation_key": frappe.generate_hash(length=64),
					"run_generation": 1,
					"revisit_at": revisit_at,
					"reevaluation_trigger": trigger,
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
			return doc.name

		def _automatic_runs(self):
			return frappe.get_all(
				nba_evaluations.DOCTYPE,
				filters={
					"student": self.student,
					"trigger": "automatic",
					"status": ["in", ["queued", "running"]],
				},
				pluck="name",
			)

		def test_wait_commit_persists_the_revisit_boundary(self):
			receipt = nba_evaluations.request_nba_evaluation(
				student=self.student,
				idempotency_key=f"wait-persist-{frappe.generate_hash(length=8)}",
				force_reason="wait boundary coverage",
			)
			claim = nba_evaluations.claim_nba_evaluation(evaluation=receipt["evaluation"], run_generation=0)
			nba_evaluations.commit_nba_evaluation_result(
				evaluation=claim["evaluation"],
				run_generation=claim["run_generation"],
				lease_token=claim["lease_token"],
				run_status="completed",
				disposition="WAIT",
				result_digest="a" * 64,
				trace_digest="b" * 64,
				revisit_at="2026-09-10T00:00:00+00:00",
				reevaluation_trigger="inbound_reply",
				recommendations=[],
			)
			row = frappe.db.get_value(
				nba_evaluations.DOCTYPE,
				claim["evaluation"],
				["disposition", "revisit_at", "reevaluation_trigger", "reevaluation_dispatched_at"],
				as_dict=True,
			)
			self.assertEqual(row.disposition, "WAIT")
			self.assertEqual(str(row.revisit_at), "2026-09-10 00:00:00")
			self.assertEqual(row.reevaluation_trigger, "inbound_reply")
			self.assertIsNone(row.reevaluation_dispatched_at)

		def test_due_revisit_dispatches_one_automatic_evaluation(self):
			name = self._completed_wait(revisit_at=add_to_date(now_datetime(), minutes=-5))
			result = nba_evaluations.reconcile_due_reevaluations()
			self.assertTrue(result["enabled"])
			self.assertEqual(result["due"], 1)
			self.assertEqual(result["dispatched"], 1)
			self.assertTrue(frappe.db.get_value(nba_evaluations.DOCTYPE, name, "reevaluation_dispatched_at"))
			self.assertEqual(len(self._automatic_runs()), 1)

		def test_future_revisit_is_not_dispatched(self):
			self._completed_wait(revisit_at=add_to_date(now_datetime(), days=3))
			result = nba_evaluations.reconcile_due_reevaluations()
			self.assertEqual(result["due"], 0)
			self.assertEqual(self._automatic_runs(), [])

		def test_second_pass_is_idempotent_and_burst_is_coalesced(self):
			past = add_to_date(now_datetime(), minutes=-10)
			self._completed_wait(revisit_at=past)
			self._completed_wait(revisit_at=past)
			first = nba_evaluations.reconcile_due_reevaluations()
			self.assertEqual(first["due"], 2)
			# Two due boundaries, one student identity -> a single fresh run.
			self.assertEqual(first["dispatched"], 1)
			self.assertEqual(len(self._automatic_runs()), 1)
			second = nba_evaluations.reconcile_due_reevaluations()
			self.assertEqual(second["due"], 0)
			self.assertEqual(second["dispatched"], 0)

		def test_domain_event_dispatches_a_pure_event_name_wait(self):
			"""A WAIT with no ``revisit_at`` is never picked up by the time-based
			reconciler; the domain-event admission path fires and stamps it."""
			name = self._completed_wait(revisit_at=None, trigger="inbound_reply")
			result = nba_evaluations.request_domain_reevaluation(self.student, trigger_reason="inbound_reply")

			self.assertTrue(result["enabled"])
			self.assertIsNotNone(result["created"])
			self.assertFalse(result["coalesced"])
			self.assertEqual(result["matched_waits"], 1)
			self.assertTrue(frappe.db.get_value(nba_evaluations.DOCTYPE, name, "reevaluation_dispatched_at"))
			self.assertEqual(len(self._automatic_runs()), 1)

		def test_domain_event_burst_for_one_student_coalesces_to_one_run(self):
			"""A second domain event for the same student while the first
			evaluation is still queued/running merges into it -- no duplicate
			concurrent evaluation is created."""
			self._completed_wait(revisit_at=None, trigger="inbound_reply")
			first = nba_evaluations.request_domain_reevaluation(self.student, trigger_reason="inbound_reply")
			self.assertIsNotNone(first["created"])

			second = nba_evaluations.request_domain_reevaluation(self.student, trigger_reason="inbound_reply")

			self.assertIsNone(second["created"])
			self.assertTrue(second["coalesced"])
			self.assertEqual(len(self._automatic_runs()), 1)

		def test_domain_event_with_no_matching_wait_is_a_disabled_flag_free_no_op(self):
			result = nba_evaluations.request_domain_reevaluation(self.student, trigger_reason="")
			self.assertEqual(
				result, {"enabled": True, "created": None, "coalesced": False, "matched_waits": 0}
			)

		def _insert_terminal_run_over_the_current_identity(self, *, disposition="NO_ACTION"):
			"""Insert a settled run whose identity is the one freshly computed for
			``self.student`` right now, so `_latest_terminal` matches it exactly."""
			clock = nba_evaluations._request_clock()
			_, identity = nba_evaluations._identity_for(self.student, clock)
			frappe.get_doc(
				{
					"doctype": nba_evaluations.DOCTYPE,
					"student": self.student,
					"trigger": "automatic",
					"status": "completed",
					"disposition": disposition,
					"engine_revision": "nba-engine-test",
					"evaluation_key": identity["evaluation_key"],
					"context_revision": identity["context_revision"],
					"context_digest": identity["context_digest"],
					"eligible_set_revision": identity["eligible_set_revision"],
					"eligible_set_digest": identity["eligible_set_digest"],
					"library_digest": identity["library_digest"],
					"decision_policy_revision": identity["decision_policy_revision"],
					"decision_digest": identity["decision_digest"],
					"eligibility_digest": identity["eligibility_digest"],
					"timing_digest": identity["timing_digest"],
					"evaluation_clock": clock,
					"run_generation": 1,
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()

		def test_identity_unchanged_terminal_run_leaves_the_wait_unstamped_and_retryable(self):
			"""`_request_automatic_nba_evaluation` returns ``None`` (no new run, no
			merge) when the governed identity has not moved since the last terminal
			run. The matched WAIT boundary must stay unstamped, or the trigger is
			permanently excluded from both the scheduler sweep and future
			domain-event matching with no run ever created -- a lost wakeup."""
			self._insert_terminal_run_over_the_current_identity()
			name = self._completed_wait(revisit_at=None, trigger="identity-unchanged")

			result = nba_evaluations.request_domain_reevaluation(
				self.student, trigger_reason="identity-unchanged"
			)

			self.assertIsNone(result["created"])
			self.assertTrue(result["coalesced"])
			self.assertEqual(result["matched_waits"], 1)
			self.assertIsNone(
				frappe.db.get_value(nba_evaluations.DOCTYPE, name, "reevaluation_dispatched_at")
			)
			self.assertEqual(self._automatic_runs(), [])

			# Unstamped -> a later event still finds and can retry the boundary.
			again = nba_evaluations.request_domain_reevaluation(
				self.student, trigger_reason="identity-unchanged"
			)
			self.assertEqual(again["matched_waits"], 1)

		def test_domain_reevaluation_locks_before_reading_matched_wait_rows(self):
			"""The Student-row lock must be this transaction's first statement, so
			the matched-WAIT-rows read runs inside the locked scope -- never as a
			plain pre-lock read that could pin the REPEATABLE READ snapshot ahead
			of the lock and miss a concurrently committed run."""
			self._completed_wait(revisit_at=None, trigger="order-check")
			order = []
			original_sql = frappe.db.sql
			original_get_all = frappe.get_all

			def tracking_sql(query, *args, **kwargs):
				if "FOR UPDATE" in str(query) and "tabCRM Student" in str(query):
					order.append("lock")
				return original_sql(query, *args, **kwargs)

			def tracking_get_all(doctype, *args, **kwargs):
				filters = kwargs.get("filters") or (args[0] if args else {})
				if (
					doctype == nba_evaluations.DOCTYPE
					and isinstance(filters, dict)
					and "reevaluation_trigger" in filters
				):
					order.append("matched_waits_read")
				return original_get_all(doctype, *args, **kwargs)

			with (
				patch("frappe.db.sql", side_effect=tracking_sql),
				patch("frappe.get_all", side_effect=tracking_get_all),
			):
				nba_evaluations.request_domain_reevaluation(self.student, trigger_reason="order-check")

			self.assertEqual(order, ["lock", "matched_waits_read"])


if __name__ == "__main__":
	unittest.main()
