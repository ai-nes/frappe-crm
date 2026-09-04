# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Validator coverage for evaluation-scoped CRM Recommendation rows.

An evaluation-scoped recommendation carries the immutable kernel payload and is
frozen once persisted: the owning evaluation, its kernel key, rank, payload and
action can never change. Legacy rows -- those with no linked evaluation -- keep
their existing mutable projection. One evaluation may not hold two rows for the
same kernel key.
"""

import unittest

try:
	import frappe
	from frappe.tests.utils import FrappeTestCase
except Exception:  # pragma: no cover - pure environment without a bench
	FrappeTestCase = None


if FrappeTestCase is not None:

	class TestNbaRecommendationCommit(FrappeTestCase):
		@classmethod
		def setUpClass(cls):
			if not getattr(frappe, "db", None):
				raise unittest.SkipTest(
					"NBA Recommendation commit tests require a bench site (use bench run-tests)"
				)
			super().setUpClass()
			student = frappe.get_all("CRM Student", pluck="name", limit_page_length=1)
			if not student:
				raise unittest.SkipTest("no seeded CRM Student on this site")
			cls.student = student[0]

		def setUp(self):
			self._cleanup()

		def tearDown(self):
			self._cleanup()

		def _cleanup(self):
			frappe.db.delete("CRM Recommendation", {"target_id": self.student})
			frappe.db.delete("CRM NBA Evaluation", {"student": self.student})
			frappe.db.commit()

		def _evaluation(self):
			doc = frappe.get_doc(
				{
					"doctype": "CRM NBA Evaluation",
					"student": self.student,
					"trigger": "manual",
					"status": "queued",
					"engine_revision": "nba-engine-test",
					"evaluation_key": frappe.generate_hash(length=64),
				}
			).insert(ignore_permissions=True)
			return doc.name

		def _insert(self, values):
			doc = frappe.get_doc(values)
			# These scenarios exercise the controller only; the CRM Staff ``owner``
			# link is immaterial and unset on the bench's Administrator session.
			doc.flags.ignore_links = True
			return doc.insert(ignore_permissions=True)

		def _save(self, doc):
			doc.flags.ignore_links = True
			return doc.save(ignore_permissions=True)

		def _epoch_recommendation(self, evaluation, *, rank=1, key="rk-1"):
			return self._insert(
				{
					"doctype": "CRM Recommendation",
					"recommendation_id": f"{evaluation}-{rank}",
					"target_type": "CRM Student",
					"target_id": self.student,
					"reason": "kernel recommendation",
					"priority": "medium",
					"evaluation": evaluation,
					"recommendation_key": key,
					"rank": rank,
					"ai_payload": {"recommendation_key": key, "rank": rank},
				}
			)

		def _legacy_recommendation(self):
			return self._insert(
				{
					"doctype": "CRM Recommendation",
					"recommendation_id": f"REC-legacy-{frappe.generate_hash(length=8)}",
					"target_type": "CRM Student",
					"target_id": self.student,
					"reason": "legacy recommendation",
					"priority": "medium",
				}
			)

		def test_epoch_payload_is_frozen(self):
			row = self._epoch_recommendation(self._evaluation())
			row.reload()
			row.ai_payload = {"recommendation_key": "rk-1", "rank": 1, "tampered": True}
			with self.assertRaises(frappe.ValidationError):
				self._save(row)

		def test_epoch_rank_and_key_are_frozen(self):
			evaluation = self._evaluation()
			row = self._epoch_recommendation(evaluation)

			row.reload()
			row.rank = 5
			with self.assertRaises(frappe.ValidationError):
				self._save(row)

			fresh = frappe.get_doc("CRM Recommendation", row.name)
			fresh.recommendation_key = "rk-2"
			with self.assertRaises(frappe.ValidationError):
				self._save(fresh)

			fresh = frappe.get_doc("CRM Recommendation", row.name)
			fresh.evaluation = None
			with self.assertRaises(frappe.ValidationError):
				self._save(fresh)

		def test_epoch_row_tolerates_a_no_op_save(self):
			row = self._epoch_recommendation(self._evaluation())
			row.reload()
			row.lifecycle_status = "active"
			self._save(row)

		def test_legacy_row_stays_mutable(self):
			row = self._legacy_recommendation()
			row.reload()
			row.purpose = "changed purpose"
			row.priority = "high"
			self._save(row)
			self.assertEqual(frappe.db.get_value("CRM Recommendation", row.name, "priority"), "high")

		def test_duplicate_kernel_key_within_evaluation_is_rejected(self):
			evaluation = self._evaluation()
			self._epoch_recommendation(evaluation, rank=1, key="rk-dup")
			with self.assertRaises(frappe.ValidationError):
				self._epoch_recommendation(evaluation, rank=2, key="rk-dup")

		def test_same_kernel_key_across_evaluations_is_allowed(self):
			first = self._epoch_recommendation(self._evaluation(), rank=1, key="rk-shared")
			second = self._epoch_recommendation(self._evaluation(), rank=1, key="rk-shared")
			self.assertNotEqual(first.name, second.name)


if FrappeTestCase is not None:
	from crm.fcrm import nba_evaluations

	class TestNbaEvaluationResultCommit(FrappeTestCase):
		"""The fenced ``commit_nba_evaluation_result`` transaction end to end."""

		@classmethod
		def setUpClass(cls):
			if not getattr(frappe, "db", None):
				raise unittest.SkipTest("commit tests require a bench site (use bench run-tests)")
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

		def _claimed(self, suffix):
			receipt = nba_evaluations.request_nba_evaluation(
				student=self.student,
				idempotency_key=f"commit-{suffix}-{frappe.generate_hash(length=8)}",
				force_reason="commit coverage exercise",
			)
			return nba_evaluations.claim_nba_evaluation(evaluation=receipt["evaluation"], run_generation=0)

		def _recommendation(self, *, rank, key):
			return {
				"recommendation_key": key,
				"rank": rank,
				"action_ref": {
					"action_id": "ACT-UNSEEDED",
					"action_revision": 1,
					"action_digest": "a" * 64,
				},
				"opportunity_refs": [],
				"recommended_execution_params": {},
				"recommended_timing": {
					"earliest_at": None,
					"latest_at": None,
					"scheduled_at": "2026-09-10T00:00:00+00:00",
					"timezone": "Asia/Ho_Chi_Minh",
				},
				"score": {"total": 0.7},
				"confidence": 0.6,
				"reason_codes": ["ENGAGE_OR_REENGAGE"],
				"evidence_refs": [],
				"explanation_facts": [f"Rank {rank} rationale."],
				"conflict_keys": [f"action:{rank}"],
				"expires_at": "2026-09-20T00:00:00+00:00",
			}

		def _commit(self, claim, **over):
			payload = dict(
				evaluation=claim["evaluation"],
				run_generation=claim["run_generation"],
				lease_token=claim["lease_token"],
				engine_revision=claim.get("engine_revision") or "nba-engine-v0",
				run_status="completed",
				disposition="RECOMMEND",
				result_digest="a" * 64,
				trace_digest="b" * 64,
				recommendations=[self._recommendation(rank=1, key="rk-1")],
				trace_entries=[{"kind": "candidate", "rank": 1}],
			)
			payload.update(over)
			return nba_evaluations.commit_nba_evaluation_result(**payload)

		def _action_items(self):
			return frappe.db.count("CRM Action Item", {"student": self.student})

		# --- valid RECOMMEND -------------------------------------------------- #
		def test_recommend_writes_evaluation_and_top_n_rows_and_no_action_item(self):
			claim = self._claimed("recommend")
			before_items = self._action_items()
			receipt = self._commit(
				claim,
				recommendations=[
					self._recommendation(rank=1, key="rk-1"),
					self._recommendation(rank=2, key="rk-2"),
				],
			)
			self.assertEqual(receipt["status"], "accepted")
			self.assertEqual(
				receipt["recommendation_ids"],
				[f"{claim['evaluation']}-1", f"{claim['evaluation']}-2"],
			)
			row = frappe.db.get_value(
				nba_evaluations.DOCTYPE,
				claim["evaluation"],
				["status", "disposition", "recommendation_count", "result_digest", "evaluation_trace"],
				as_dict=True,
			)
			self.assertEqual(
				(row.status, row.disposition, row.recommendation_count), ("completed", "RECOMMEND", 2)
			)
			self.assertEqual(row.result_digest, "a" * 64)
			self.assertTrue(row.evaluation_trace)
			ranks = frappe.get_all(
				"CRM Recommendation",
				filters={"evaluation": claim["evaluation"]},
				fields=["`rank`", "recommendation_key"],
				order_by="`rank` asc",
			)
			self.assertEqual([r["rank"] for r in ranks], [1, 2])
			self.assertEqual(self._action_items(), before_items)

		# --- WAIT / NO_ACTION / ABSTAIN ------------------------------------- #
		def test_non_recommend_dispositions_write_only_the_evaluation(self):
			for disposition, extra in (
				("WAIT", {"reevaluation_trigger": "inbound_reply"}),
				("NO_ACTION", {}),
				("ABSTAIN", {}),
			):
				claim = self._claimed(f"disp-{disposition.lower()}")
				receipt = self._commit(claim, disposition=disposition, recommendations=[], **extra)
				self.assertEqual(receipt["status"], "accepted")
				self.assertEqual(receipt["recommendation_ids"], [])
				self.assertEqual(
					frappe.db.get_value(nba_evaluations.DOCTYPE, claim["evaluation"], "disposition"),
					disposition,
				)
				self.assertEqual(
					frappe.db.count("CRM Recommendation", {"evaluation": claim["evaluation"]}), 0
				)

		def test_wait_without_revisit_or_trigger_is_rejected(self):
			claim = self._claimed("wait-bare")
			with self.assertRaises(frappe.ValidationError):
				self._commit(claim, disposition="WAIT", recommendations=[])

		# --- stale / superseded ------------------------------------------- #
		def test_identity_drift_supersedes_with_zero_rows(self):
			claim = self._claimed("stale")
			frappe.db.set_value(
				nba_evaluations.DOCTYPE,
				claim["evaluation"],
				"eligible_set_digest",
				"9" * 64,
				update_modified=False,
			)
			receipt = self._commit(
				claim,
				recommendations=[self._recommendation(rank=1, key="rk-1")],
			)
			self.assertEqual(receipt["status"], "superseded")
			self.assertEqual(receipt["recommendation_ids"], [])
			self.assertEqual(receipt["terminal_reason"], "superseded")
			row = frappe.db.get_value(
				nba_evaluations.DOCTYPE,
				claim["evaluation"],
				["status", "terminal_reason", "disposition"],
				as_dict=True,
			)
			self.assertEqual(
				(row.status, row.terminal_reason, row.disposition), ("failed", "superseded", None)
			)
			self.assertEqual(frappe.db.count("CRM Recommendation", {"evaluation": claim["evaluation"]}), 0)

		# --- duplicate delivery ----------------------------------------- #
		def test_duplicate_delivery_returns_the_same_receipt_without_dupes(self):
			claim = self._claimed("dup")
			recs = [self._recommendation(rank=1, key="rk-1"), self._recommendation(rank=2, key="rk-2")]
			first = self._commit(claim, recommendations=recs)
			second = self._commit(claim, recommendations=recs)
			self.assertEqual(first["recommendation_ids"], second["recommendation_ids"])
			self.assertEqual(second["status"], "accepted")
			self.assertEqual(frappe.db.count("CRM Recommendation", {"evaluation": claim["evaluation"]}), 2)

		def test_terminal_replay_after_supersede_returns_superseded(self):
			claim = self._claimed("replay-stale")
			frappe.db.set_value(
				nba_evaluations.DOCTYPE,
				claim["evaluation"],
				"eligible_set_digest",
				"9" * 64,
				update_modified=False,
			)
			self._commit(claim)
			replay = self._commit(claim)
			self.assertEqual(replay["status"], "superseded")
			self.assertEqual(replay["recommendation_ids"], [])

		# --- conflict / over-cap -------------------------------------- #
		def test_over_cap_is_rejected_atomically(self):
			claim = self._claimed("overcap")
			recs = [self._recommendation(rank=i + 1, key=f"rk-{i}") for i in range(11)]
			with self.assertRaises(frappe.ValidationError):
				self._commit(claim, recommendations=recs)
			self.assertEqual(
				frappe.db.get_value(nba_evaluations.DOCTYPE, claim["evaluation"], "status"), "running"
			)
			self.assertEqual(frappe.db.count("CRM Recommendation", {"evaluation": claim["evaluation"]}), 0)

		def test_non_dense_ranks_are_rejected(self):
			claim = self._claimed("ranks")
			recs = [self._recommendation(rank=1, key="rk-1"), self._recommendation(rank=3, key="rk-3")]
			with self.assertRaises(frappe.ValidationError):
				self._commit(claim, recommendations=recs)

		def test_fence_mismatch_is_rejected(self):
			claim = self._claimed("fence")
			with self.assertRaises(frappe.ValidationError):
				self._commit(claim, lease_token="not-the-live-token")

		# --- mid-transaction failure ------------------------------ #
		def test_mid_transaction_failure_rolls_back_everything(self):
			claim = self._claimed("rollback")
			recs = [self._recommendation(rank=1, key="rk-1"), self._recommendation(rank=2, key="rk-2")]
			original = nba_evaluations._committed_recommendation_priority
			calls = {"n": 0}

			def boom(rank):
				calls["n"] += 1
				if calls["n"] == 2:
					raise RuntimeError("recommendation insert failed")
				return original(rank)

			nba_evaluations._committed_recommendation_priority = boom
			try:
				with self.assertRaises(RuntimeError):
					self._commit(claim, recommendations=recs)
			finally:
				nba_evaluations._committed_recommendation_priority = original
			frappe.db.rollback()
			self.assertEqual(frappe.db.count("CRM Recommendation", {"target_id": self.student}), 0)
			status = frappe.db.get_value(nba_evaluations.DOCTYPE, claim["evaluation"], "status")
			self.assertNotIn(status, nba_evaluations.TERMINAL)

		# --- payload mutation rejected by the 05a validator ------ #
		def test_committed_recommendation_payload_is_immutable(self):
			claim = self._claimed("frozen")
			receipt = self._commit(claim)
			row = frappe.get_doc("CRM Recommendation", receipt["recommendation_ids"][0])
			row.ai_payload = {"recommendation_key": "rk-1", "rank": 1, "tampered": True}
			row.flags.ignore_links = True
			with self.assertRaises(frappe.ValidationError):
				row.save(ignore_permissions=True)

		# --- rank carries no Task / Action Item semantics -------- #
		def test_commit_creates_zero_action_item_rows(self):
			claim = self._claimed("no-task")
			before = self._action_items()
			self._commit(
				claim,
				recommendations=[
					self._recommendation(rank=1, key="rk-1"),
					self._recommendation(rank=2, key="rk-2"),
					self._recommendation(rank=3, key="rk-3"),
				],
			)
			self.assertEqual(self._action_items(), before)


if FrappeTestCase is not None:
	from crm.fcrm import nba_evaluations

	class TestRecommendationRationale(FrappeTestCase):
		"""``set_recommendation_rationale``: fenced, idempotent, write-once."""

		@classmethod
		def setUpClass(cls):
			if not getattr(frappe, "db", None):
				raise unittest.SkipTest("rationale tests require a bench site (use bench run-tests)")
			super().setUpClass()
			cls._conf_backup = {key: frappe.conf.get(key) for key in ("crm_agents_service_user",)}
			frappe.conf["crm_agents_service_user"] = "Administrator"
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
			frappe.db.delete("CRM Recommendation", {"target_id": self.student})
			frappe.db.commit()

		def tearDown(self):
			frappe.db.delete("CRM Recommendation", {"target_id": self.student})
			frappe.db.commit()

		def _recommendation(self):
			doc = frappe.get_doc(
				{
					"doctype": "CRM Recommendation",
					"recommendation_id": "REC-rationale-" + frappe.generate_hash(length=10),
					"target_type": "CRM Student",
					"target_id": self.student,
					"reason": "kernel recommendation",
					"priority": "medium",
				}
			)
			doc.flags.ignore_links = True
			return doc.insert(ignore_permissions=True)

		def _explanation(self, **overrides):
			base = {
				"action": {"code": "ACT-CALL", "title": "ACT-CALL"},
				"summary": "Học viên đang ở giai đoạn cân nhắc học phí.",
				"why_action": "Hành động này phù hợp vì học viên đã hỏi về học phí.",
				"why_now": "Học viên im lặng 9 ngày sau khi hỏi về học phí, nên gọi ngay.",
				"evidence": [
					{
						"summary": "Học viên đã hỏi về học phí trước khi im lặng.",
						"evidence_ref": "interaction:CRMI-1001",
					}
				],
				"uncertainty": "Độ tin cậy ở mức trung bình vì dữ liệu tương tác còn ít.",
				"timing": {
					"recommended_at": "2026-09-10T00:00:00+00:00",
					"reason": "Thời điểm đề xuất nằm trong khung giờ khả thi.",
				},
			}
			base.update(overrides)
			return base

		def test_first_set_succeeds(self):
			rec = self._recommendation()
			explanation = self._explanation()
			result = nba_evaluations.set_recommendation_rationale(
				recommendation=rec.name,
				explanation=explanation,
				source="model",
			)
			self.assertEqual(result["status"], "set")
			stored = frappe.parse_json(frappe.db.get_value("CRM Recommendation", rec.name, "explanation"))
			self.assertEqual(stored["summary"], explanation["summary"])
			self.assertEqual(stored["evidence"], explanation["evidence"])
			self.assertEqual(frappe.db.get_value("CRM Recommendation", rec.name, "rationale_source"), "model")

		def test_same_value_replay_is_idempotent(self):
			rec = self._recommendation()
			explanation = self._explanation()
			first = nba_evaluations.set_recommendation_rationale(
				recommendation=rec.name, explanation=explanation, source="model"
			)
			second = nba_evaluations.set_recommendation_rationale(
				recommendation=rec.name, explanation=dict(explanation), source="model"
			)
			self.assertEqual(first["status"], "set")
			self.assertEqual(second["status"], "unchanged")

		def test_differing_overwrite_is_rejected(self):
			rec = self._recommendation()
			nba_evaluations.set_recommendation_rationale(
				recommendation=rec.name, explanation=self._explanation(), source="model"
			)
			with self.assertRaises(frappe.ValidationError):
				nba_evaluations.set_recommendation_rationale(
					recommendation=rec.name,
					explanation=self._explanation(summary="Bản khác hẳn."),
					source="model",
				)
			stored = frappe.parse_json(frappe.db.get_value("CRM Recommendation", rec.name, "explanation"))
			self.assertNotEqual(stored["summary"], "Bản khác hẳn.")

		def test_unrecognised_source_is_rejected(self):
			rec = self._recommendation()
			with self.assertRaises(frappe.ValidationError):
				nba_evaluations.set_recommendation_rationale(
					recommendation=rec.name, explanation=self._explanation(), source="human"
				)

		def test_empty_explanation_is_rejected(self):
			rec = self._recommendation()
			with self.assertRaises(frappe.ValidationError):
				nba_evaluations.set_recommendation_rationale(
					recommendation=rec.name, explanation={}, source="model"
				)

		def test_missing_field_is_rejected(self):
			rec = self._recommendation()
			explanation = self._explanation()
			del explanation["uncertainty"]
			with self.assertRaises(frappe.ValidationError):
				nba_evaluations.set_recommendation_rationale(
					recommendation=rec.name, explanation=explanation, source="model"
				)

		def test_non_service_caller_is_rejected(self):
			rec = self._recommendation()
			frappe.conf["crm_agents_service_user"] = "someone-else@example.com"
			try:
				with self.assertRaises(frappe.PermissionError):
					nba_evaluations.set_recommendation_rationale(
						recommendation=rec.name, explanation=self._explanation(), source="model"
					)
			finally:
				frappe.conf["crm_agents_service_user"] = "Administrator"

		def test_doctype_controller_rejects_a_differing_overwrite_on_save(self):
			rec = self._recommendation()
			rec.explanation = self._explanation()
			rec.flags.ignore_links = True
			rec.save(ignore_permissions=True)

			fresh = frappe.get_doc("CRM Recommendation", rec.name)
			fresh.explanation = self._explanation(summary="Bản khác qua ORM.")
			fresh.flags.ignore_links = True
			with self.assertRaises(frappe.ValidationError):
				fresh.save(ignore_permissions=True)

		def test_doctype_controller_tolerates_a_no_op_save(self):
			rec = self._recommendation()
			explanation = self._explanation()
			rec.explanation = explanation
			rec.flags.ignore_links = True
			rec.save(ignore_permissions=True)

			fresh = frappe.get_doc("CRM Recommendation", rec.name)
			fresh.priority = "high"
			fresh.flags.ignore_links = True
			fresh.save(ignore_permissions=True)
			stored = frappe.parse_json(frappe.get_doc("CRM Recommendation", rec.name).explanation)
			self.assertEqual(stored["summary"], explanation["summary"])


if __name__ == "__main__":
	unittest.main()
