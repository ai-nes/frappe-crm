# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Bench contract for the automatic-Run admission provenance surface.

``intelligence_runs.execution`` is the only read the crm-agents worker uses to
bind a Next Best Action to the Frappe-owned admission decision. This asserts the
four provenance fields (`admission_decision`, `admission_event`,
`candidate_revision`, `policy_revision`) round-trip, and that a manual run --
which has no admission decision -- reports them as absent with the candidate
revision falling back to the run's source revision.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm import intelligence_runs

_RUN_TYPE = "CRM Student Analysis Run"
_RULE_IDENTITY = {
	"rule_version": "CURRENT",
	"rule_version_digest": "a" * 64,
	"ruleset_digest": "a" * 64,
}


class TestIntelligenceRunProvenance(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self._prev_service_user = frappe.conf.get(intelligence_runs.SERVICE_USER_KEY)
		frappe.conf[intelligence_runs.SERVICE_USER_KEY] = "Administrator"
		self._student = self._make_student("_Provenance Student")
		self._runs: list[str] = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for run in self._runs:
			frappe.db.delete("CRM Analysis Run Stage", {"parent_run": run})
			frappe.db.delete(_RUN_TYPE, {"name": run})
		frappe.delete_doc("CRM Student", self._student.name, force=True)
		if self._prev_service_user is None:
			frappe.conf.pop(intelligence_runs.SERVICE_USER_KEY, None)
		else:
			frappe.conf[intelligence_runs.SERVICE_USER_KEY] = self._prev_service_user

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Student", "full_name": name, "phone": phone})
		student.insert(ignore_permissions=True)
		return student

	def _make_run(self, *, trigger, revision, **extra):
		digest = frappe.generate_hash(length=32) + frappe.generate_hash(length=32)
		values = {
			"doctype": _RUN_TYPE,
			"student": self._student.name,
			"source_revision": revision,
			"source_digest": digest,
			"trigger": trigger,
			"status": "queued",
			"request_fingerprint": frappe.generate_hash(length=32) + frappe.generate_hash(length=32),
			**_RULE_IDENTITY,
		}
		if trigger == "automatic":
			values["automatic_identity"] = frappe.generate_hash(length=48)
		else:
			values["requested_by"] = frappe.session.user
		values.update(extra)
		run = frappe.get_doc(values).insert(ignore_permissions=True)
		self._runs.append(run.name)
		frappe.get_doc(
			{
				"doctype": "CRM Analysis Run Stage",
				"parent_run_type": _RUN_TYPE,
				"parent_run": run.name,
				"stage_kind": "student_360",
				"stage_key": f"{_RUN_TYPE}:{run.name}:student_360",
				"stage_generation": 0,
				"status": "queued",
				"expected_source_revision": str(revision),
				"expected_source_digest": digest,
				**_RULE_IDENTITY,
			}
		).insert(ignore_permissions=True)
		return run

	def test_automatic_run_execution_exposes_admission_provenance(self):
		decision = frappe.get_doc(
			{
				"doctype": "CRM Admission Event Decision",
				"decision_id": frappe.generate_hash(length=32),
				"decision_key": f"admission-v1:{frappe.generate_hash(length=16)}",
				"source_event": "JRNL-PROV-1",
				"event_type": "lifecycle_transition",
				"student": self._student.name,
				"candidate_revision": 4,
				"policy_version": "admission-v1",
				"outcome": "admitted",
				"reason": "enqueued",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Admission Event Decision", decision.name, force=True)

		run = self._make_run(
			trigger="automatic",
			revision=4,
			admission_decision=decision.name,
			admission_event="JRNL-PROV-1",
			candidate_revision=4,
			policy_revision="admission-v1",
		)

		result = intelligence_runs.execution(_RUN_TYPE, run.name)

		self.assertEqual(result["trigger"], "automatic")
		self.assertEqual(result["admission_decision"], decision.name)
		self.assertEqual(result["admission_event"], "JRNL-PROV-1")
		self.assertEqual(result["candidate_revision"], "4")
		self.assertEqual(result["policy_revision"], "admission-v1")
		self.assertEqual([s["stage_kind"] for s in result["stages"]], ["student_360"])

	def test_manual_run_execution_reports_no_admission_provenance(self):
		run = self._make_run(trigger="manual", revision=9)

		result = intelligence_runs.execution(_RUN_TYPE, run.name)

		self.assertEqual(result["trigger"], "manual")
		self.assertIsNone(result["admission_decision"])
		self.assertIsNone(result["admission_event"])
		self.assertIsNone(result["policy_revision"])
		self.assertEqual(result["candidate_revision"], "9")

	def test_execution_is_restricted_to_the_service_identity(self):
		run = self._make_run(trigger="manual", revision=1)
		frappe.conf.pop(intelligence_runs.SERVICE_USER_KEY, None)
		with self.assertRaises(frappe.PermissionError):
			intelligence_runs.execution(_RUN_TYPE, run.name)


class TestStudentEvidenceHistoryProvenance(FrappeTestCase):
	"""Interaction history rows must carry only what belongs to that
	interaction: the newest intent analysed for it, no student-level barrier."""

	def _evidence(self, intents):
		from unittest.mock import patch

		row = {
			"student_stage": "Connected",
			"primary_barrier": "Học phí",
			"score_input_revision": 9,
			"applied_score_input_revision": 9,
		}
		rows_by_doctype = {
			"CRM Score History": [],
			"CRM Interaction": [
				{"name": "I-NEW", "interaction_datetime": "2026-02-01", "source_verified": 1, "actor": "staff@example.com"},
				{"name": "I-OLD", "interaction_datetime": "2026-01-01", "source_verified": 1, "actor": None},
			],
			"CRM Intent": intents,
			"CRM Admission Application": [],
			"CRM Student Guardian": [],
		}
		calls = []

		def fake_get_all(doctype, **kwargs):
			calls.append((doctype, kwargs))
			return rows_by_doctype[doctype]

		with (
			patch("crm.fcrm.intelligence_runs.frappe.db.get_value", return_value=row),
			patch("crm.fcrm.intelligence_runs.frappe.get_all", side_effect=fake_get_all),
			patch("crm.fcrm.intelligence_runs.frappe.db.count", return_value=37),
			patch("crm.fcrm.intelligence_runs.frappe.db.table_exists", return_value=True),
		):
			payload = intelligence_runs._student_stage_evidence("STU-1", "9")["student_360"]
		return payload, calls

	def test_newest_intent_per_interaction_wins_and_is_queried_by_interaction_set(self):
		# Rows arrive newest-first, as the producer orders them.
		payload, calls = self._evidence([
			{"name": "INT-3", "interaction": "I-NEW", "intent_type": "Amended", "polarity": "Positive", "intent_role": "Dominant", "confidence": 80},
			{"name": "INT-2", "interaction": "I-NEW", "intent_type": "Superseded", "polarity": "Negative", "intent_role": "Support", "confidence": 40},
			{"name": "INT-1", "interaction": "I-OLD", "intent_type": "Initial", "polarity": "Positive", "intent_role": "Dominant", "confidence": 60},
		])
		history = {item["provenance_ids"][0]: item for item in payload["signals"]["interaction_history"]}
		self.assertEqual(history["interaction:I-NEW"]["intent_type"], "Amended")
		self.assertEqual(history["interaction:I-NEW"]["intent_role"], "Dominant")
		self.assertEqual(history["interaction:I-OLD"]["intent_type"], "Initial")
		self.assertEqual(payload["signals"]["intent_type"], "Amended")
		intent_query = next(kwargs for doctype, kwargs in calls if doctype == "CRM Intent")
		self.assertEqual(intent_query["filters"]["interaction"], ["in", ["I-NEW", "I-OLD"]])
		# The interaction set is the only bound: a row cap would let a heavily
		# re-analysed interaction crowd an older one out of the window again.
		self.assertEqual(intent_query["limit_page_length"], 0)

	def test_history_rows_carry_no_barrier_but_actor_kind_while_current_block_keeps_barrier(self):
		payload, _ = self._evidence([])
		rows = payload["signals"]["interaction_history"]
		self.assertEqual([item["barriers"] for item in rows], [[], []])
		self.assertEqual([item["actor_kind"] for item in rows], ["staff", "system"])
		self.assertTrue(all(item["intent_type"] is None for item in rows))
		self.assertEqual(payload["signals"]["primary_barrier"], "Học phí")
		self.assertNotIn("staff@example.com", str(payload))

	def test_source_coverage_discloses_the_producer_row_cap(self):
		payload, _ = self._evidence([])
		self.assertEqual(payload["source_coverage"]["interaction_history"], {"source_total": 37, "producer_limit": 20})
		interaction_coverage = next(item for item in payload["coverage"] if item["coverage_id"].endswith(":interaction_history"))
		self.assertEqual(interaction_coverage["state"], "truncated")
		self.assertEqual(interaction_coverage["included_count"], 2)
		self.assertEqual(interaction_coverage["omitted_count"], 35)
		self.assertEqual(interaction_coverage["reason"], "student_evidence_source_limit")
