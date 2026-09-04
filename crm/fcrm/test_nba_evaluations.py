# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Lifecycle coverage for the durable, feature-gated NBA Evaluation runtime.

``TestNbaEvaluationIdentity`` is pure -- it exercises the envelope-identity
projection and the digest guard without a database. ``TestNbaEvaluationLifecycle``
is a ``FrappeTestCase`` that drives request -> event -> claim -> snapshot ->
settle against a seeded student and pins the fencing, supersede, idempotent
replay, feature-gate and scope invariants.
"""

import unittest

from crm.fcrm.nba_evaluations import _bounded_hex64, _identity_from_envelope

_HEX64 = "a" * 64
_SAMPLE_ENVELOPE = {
	"contract_version": "nba-evaluation-v1",
	"evaluation_id": "NBAEVAL-0000000000000000",
	"evaluation_key": "b" * 64,
	"evaluation_clock": "2026-09-04T03:00:00+07:00",
	"student": {"student_id": "ENR-TEST", "context_revision": 7, "context_digest": "c" * 64},
	"eligible_action_set": {"set_revision": 3, "set_digest": "d" * 64, "actions": []},
	"policies": {
		"library_revision": "action-library-r3",
		"library_digest": "e" * 64,
		"eligibility_revision": "eligibility-reason-codes-v1",
		"eligibility_digest": "f" * 64,
		"decision_revision": "nba-decision-policy-r1",
		"decision_digest": "0" * 64,
		"timing_revisions": [],
		"timing_digest": "1" * 64,
	},
}


class TestNbaEvaluationIdentity(unittest.TestCase):
	def test_identity_projection_binds_every_governed_revision_and_digest(self):
		identity = _identity_from_envelope(_SAMPLE_ENVELOPE)
		self.assertEqual(identity["evaluation_key"], "b" * 64)
		self.assertEqual(identity["context_revision"], "7")
		self.assertEqual(identity["context_digest"], "c" * 64)
		self.assertEqual(identity["eligible_set_revision"], "3")
		self.assertEqual(identity["eligible_set_digest"], "d" * 64)
		self.assertEqual(identity["library_digest"], "e" * 64)
		self.assertEqual(identity["eligibility_digest"], "f" * 64)
		self.assertEqual(identity["decision_policy_revision"], "nba-decision-policy-r1")
		self.assertEqual(identity["decision_digest"], "0" * 64)
		self.assertEqual(identity["timing_digest"], "1" * 64)
		self.assertEqual(identity["evaluation_clock"], "2026-09-04T03:00:00+07:00")

	def test_bounded_hex64_accepts_valid_and_rejects_malformed(self):
		self.assertIsNone(_bounded_hex64(None, "result digest"))
		self.assertIsNone(_bounded_hex64("", "result digest"))
		self.assertEqual(_bounded_hex64(_HEX64.upper(), "result digest"), _HEX64)
		with self.assertRaises(ValueError):
			_bounded_hex64("nothex", "result digest")
		with self.assertRaises(ValueError):
			_bounded_hex64("a" * 63, "result digest")


try:
	import frappe
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - pure environment without a bench
	FrappeTestCase = None


if FrappeTestCase is not None:
	from crm.api import agent_events
	from crm.fcrm import nba_evaluations

	class TestNbaEvaluationLifecycle(FrappeTestCase):
		@classmethod
		def setUpClass(cls):
			if not getattr(frappe, "db", None):
				raise unittest.SkipTest(
					"NBA Evaluation lifecycle tests require a bench site (use bench run-tests)"
				)
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
			cls.student = frappe.get_all("CRM Student", pluck="name", limit_page_length=1)
			if not cls.student:
				raise unittest.SkipTest("no seeded CRM Student on this site")
			cls.student = cls.student[0]

		@classmethod
		def tearDownClass(cls):
			for key, value in cls._conf_backup.items():
				if value is None:
					frappe.conf.pop(key, None)
				else:
					frappe.conf[key] = value
			super().tearDownClass()

		def setUp(self):
			# ``build_nba_evaluation_input`` may commit while materialising a
			# projection, so the FrappeTestCase rollback cannot be relied on to
			# isolate this feature's own additive rows -- clear them explicitly.
			self._reset_rows()
			self._enqueue = frappe.enqueue
			frappe.enqueue = lambda *a, **k: None

		def tearDown(self):
			frappe.enqueue = self._enqueue
			self._reset_rows()

		def _reset_rows(self):
			frappe.db.delete("CRM NBA Evaluation", {"student": self.student})
			frappe.db.delete("CRM Agent Event", {"aggregate_doctype": "CRM NBA Evaluation"})
			frappe.db.commit()

		def _fresh_run(self, key_suffix):
			receipt = nba_evaluations.request_nba_evaluation(
				student=self.student,
				idempotency_key=f"regression-{key_suffix}-{frappe.generate_hash(length=8)}",
				force_reason="regression coverage exercise",
			)
			return receipt["evaluation"]

		def _claim(self, evaluation, generation=0):
			return nba_evaluations.claim_nba_evaluation(evaluation=evaluation, run_generation=generation)

		def test_duplicate_requested_event_yields_one_evaluation(self):
			name = self._fresh_run("dup-event")
			doc = frappe.get_doc(nba_evaluations.DOCTYPE, name)
			first = agent_events.record_nba_evaluation_event(doc)
			second = agent_events.record_nba_evaluation_event(doc)
			self.assertEqual(first, second)
			self.assertEqual(
				frappe.db.count("CRM Agent Event", {"delivery_key": f"nba-evaluation:{name}"}), 1
			)

		def test_same_idempotency_key_reuses_the_same_run(self):
			key = f"idem-{frappe.generate_hash(length=8)}"
			one = nba_evaluations.request_nba_evaluation(student=self.student, idempotency_key=key)
			two = nba_evaluations.request_nba_evaluation(student=self.student, idempotency_key=key)
			self.assertEqual(one["evaluation"], two["evaluation"])

		def test_claim_is_a_single_winner_and_settlement_is_generation_fenced(self):
			name = self._fresh_run("claim-cas")
			claim = self._claim(name)
			self.assertTrue(claim["claimed"])
			self.assertEqual(claim["run_generation"], 1)
			deferred = self._claim(name)
			self.assertFalse(deferred.get("claimed"))
			self.assertTrue(deferred.get("deferred"))
			# A stale generation can no longer settle once the lease is reclaimed.
			frappe.db.set_value(
				nba_evaluations.DOCTYPE,
				name,
				"lease_expires_at",
				nba_evaluations._lease_now(),
				update_modified=False,
			)
			second = self._claim(name)
			self.assertTrue(second["claimed"])
			self.assertEqual(second["run_generation"], 2)
			with self.assertRaises(frappe.ValidationError):
				nba_evaluations.settle_nba_evaluation(
					evaluation=name,
					run_generation=1,
					lease_token=claim["lease_token"],
					status="completed",
					disposition="NO_ACTION",
				)

		def test_lost_lease_settlement_is_rejected(self):
			name = self._fresh_run("lost-lease")
			claim = self._claim(name)
			frappe.db.set_value(
				nba_evaluations.DOCTYPE,
				name,
				"lease_expires_at",
				nba_evaluations._lease_now(),
				update_modified=False,
			)
			self._claim(name)  # reclaim -> generation 2, new token
			with self.assertRaises(frappe.ValidationError):
				nba_evaluations.settle_nba_evaluation(
					evaluation=name,
					run_generation=claim["run_generation"],
					lease_token=claim["lease_token"],
					status="failed",
					terminal_reason="stale worker",
				)

		def test_identity_drift_supersedes_without_committing_a_result(self):
			name = self._fresh_run("supersede")
			claim = self._claim(name)
			frappe.db.set_value(
				nba_evaluations.DOCTYPE, name, "evaluation_key", "9" * 64, update_modified=False
			)
			outcome = nba_evaluations.snapshot(evaluation=name, lease_token=claim["lease_token"])
			self.assertTrue(outcome["terminal"])
			self.assertEqual(outcome["status"], "failed")
			doc = frappe.get_doc(nba_evaluations.DOCTYPE, name)
			self.assertEqual(doc.terminal_reason, "superseded")
			self.assertFalse(doc.result_digest)
			self.assertFalse(doc.disposition)

		def test_claim_and_settle_ignore_student_360_state(self):
			# The evaluation path never creates or reads a Student Analysis Run.
			runs_before = frappe.db.count("CRM Student Analysis Run", {"student": self.student})
			name = self._fresh_run("no-360")
			claim = self._claim(name)
			snap = nba_evaluations.snapshot(evaluation=name, lease_token=claim["lease_token"])
			self.assertEqual(snap["evaluation"], name)
			settled = nba_evaluations.settle_nba_evaluation(
				evaluation=name,
				run_generation=claim["run_generation"],
				lease_token=claim["lease_token"],
				status="completed",
				disposition="WAIT",
				recommendation_count=0,
			)
			self.assertEqual(settled["status"], "completed")
			self.assertEqual(settled["disposition"], "WAIT")
			self.assertEqual(
				frappe.db.count("CRM Student Analysis Run", {"student": self.student}), runs_before
			)

		def test_run_status_is_independent_from_disposition(self):
			wait_run = self._fresh_run("disp-wait")
			claim = self._claim(wait_run)
			out = nba_evaluations.settle_nba_evaluation(
				evaluation=wait_run,
				run_generation=claim["run_generation"],
				lease_token=claim["lease_token"],
				status="completed",
				disposition="WAIT",
				recommendation_count=0,
			)
			self.assertEqual(
				(out["status"], out["disposition"], out["recommendation_count"]), ("completed", "WAIT", 0)
			)

			rec_run = self._fresh_run("disp-recommend")
			claim = self._claim(rec_run)
			out = nba_evaluations.settle_nba_evaluation(
				evaluation=rec_run,
				run_generation=claim["run_generation"],
				lease_token=claim["lease_token"],
				status="completed",
				disposition="RECOMMEND",
				result_digest="a" * 64,
				recommendation_count=2,
			)
			self.assertEqual(
				(out["status"], out["disposition"], out["recommendation_count"]),
				("completed", "RECOMMEND", 2),
			)

		def test_same_evaluation_re_settle_is_an_idempotent_replay(self):
			name = self._fresh_run("replay")
			claim = self._claim(name)
			payload = dict(
				evaluation=name,
				run_generation=claim["run_generation"],
				lease_token=claim["lease_token"],
				status="completed",
				disposition="WAIT",
				trace_digest="c" * 64,
				recommendation_count=0,
			)
			first = nba_evaluations.settle_nba_evaluation(**payload)
			self.assertNotIn("replayed", first)
			replay = nba_evaluations.settle_nba_evaluation(**payload)
			self.assertTrue(replay["replayed"])
			with self.assertRaises(frappe.ValidationError):
				nba_evaluations.settle_nba_evaluation(**{**payload, "disposition": "NO_ACTION"})

		def test_disabled_runtime_throws_and_processes_nothing(self):
			name = self._fresh_run("disabled")
			frappe.conf["crm_nba_evaluation_runtime_enabled"] = 0
			try:
				with self.assertRaises(frappe.ValidationError):
					nba_evaluations.request_nba_evaluation(
						student=self.student, idempotency_key=f"off-{frappe.generate_hash(length=8)}"
					)
				with self.assertRaises(frappe.ValidationError):
					nba_evaluations.execution(name)
				with self.assertRaises(frappe.ValidationError):
					nba_evaluations.claim_nba_evaluation(evaluation=name, run_generation=0)
				self.assertEqual(
					nba_evaluations.reconcile(), {"requeued": 0, "expired_leases": 0, "enabled": False}
				)
			finally:
				frappe.conf["crm_nba_evaluation_runtime_enabled"] = 1
			# The queued run and its outbox row remain durable across the outage.
			self.assertEqual(frappe.db.get_value(nba_evaluations.DOCTYPE, name, "status"), "queued")

		def test_out_of_scope_student_is_denied(self):
			original = frappe.has_permission

			def deny(doctype, ptype=None, doc=None, *args, **kwargs):
				if doctype == "CRM Student":
					return False
				return original(doctype, ptype, doc, *args, **kwargs)

			frappe.has_permission = deny
			try:
				with self.assertRaises(frappe.PermissionError):
					nba_evaluations.request_nba_evaluation(
						student=self.student, idempotency_key=f"scope-{frappe.generate_hash(length=8)}"
					)
			finally:
				frappe.has_permission = original


if __name__ == "__main__":
	unittest.main()
