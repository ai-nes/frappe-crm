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
		frappe.delete_doc("CRM Lead", self._student.name, force=True)
		if self._prev_service_user is None:
			frappe.conf.pop(intelligence_runs.SERVICE_USER_KEY, None)
		else:
			frappe.conf[intelligence_runs.SERVICE_USER_KEY] = self._prev_service_user

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Lead", "student_name": name, "phone": phone})
		previous = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous
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
