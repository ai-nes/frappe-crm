# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

"""Bench coverage for the deterministic admission event policy.

Before this module nothing exercised ``evaluate_admission_event`` or the
per-writer admission hooks against a real site: the policy's dedupe key, the
stale-revision ``superseded`` branch, the shadow/unified split, and the
fail-closed invalid-mode guard were all unverified.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.services.admission_event_policy import (
	POLICY_VERSION,
	admit_intent,
	admit_interaction,
	evaluate_admission_event,
)


class _StubDoc(frappe._dict):
	"""Minimal stand-in for a Frappe doc passed to an admission hook."""

	def __init__(self, *, _is_new=True, _before=None, **fields):
		super().__init__(fields)
		self.__dict__["_is_new"] = _is_new
		self.__dict__["_before"] = _before

	def is_new(self):
		return self.__dict__["_is_new"]

	def get_doc_before_save(self):
		return self.__dict__["_before"]


class TestAdmissionEventPolicy(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		frappe.conf.pop("crm_admission_event_policy_mode", None)
		self.student = self._make_student("_Test Admission Policy Student")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.conf.pop("crm_admission_event_policy_mode", None)
		frappe.db.delete("CRM Admission Event Decision", {"student": self.student.name})
		frappe.db.delete("CRM Student Revision Journal", {"student": self.student.name})
		frappe.delete_doc("CRM Student", self.student.name, force=True)

	def _make_student(self, name):
		phone = "0" + "".join(str((int(c, 16) + 1) % 10) for c in frappe.generate_hash(length=9))
		student = frappe.get_doc({"doctype": "CRM Student", "student_name": name, "phone": phone})
		previous = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			student.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous
		return student

	def _revision(self):
		return int(
			frappe.db.get_value("CRM Student", self.student.name, "student_context_revision") or 0
		)

	def _decisions(self):
		return frappe.get_all(
			"CRM Admission Event Decision",
			filters={"student": self.student.name},
			fields=["name", "outcome", "reason", "event_type", "run", "candidate_revision"],
		)

	# ------------------------------------------------------------------ core

	def test_matching_revision_is_admitted_and_shadow_creates_no_run(self):
		name = evaluate_admission_event(
			student=self.student.name,
			revision=self._revision(),
			source_event="evt-admit",
			event_type="interaction",
			source_reference="INT-1",
		)
		self.assertTrue(name)
		doc = frappe.get_doc("CRM Admission Event Decision", name)
		self.assertEqual(doc.outcome, "admitted")
		self.assertEqual(doc.reason, "enqueued")
		self.assertEqual(doc.policy_version, POLICY_VERSION)
		self.assertFalse(doc.run, "shadow mode must not create an automatic Run")

	def test_same_source_event_is_idempotent(self):
		rev = self._revision()
		first = evaluate_admission_event(
			student=self.student.name, revision=rev, source_event="evt-dup",
			event_type="intent", source_reference="X",
		)
		second = evaluate_admission_event(
			student=self.student.name, revision=rev, source_event="evt-dup",
			event_type="intent", source_reference="X",
		)
		self.assertEqual(first, second)
		self.assertEqual(
			frappe.db.count(
				"CRM Admission Event Decision", {"decision_key": f"{POLICY_VERSION}:evt-dup"}
			),
			1,
		)

	def test_stale_candidate_revision_is_superseded(self):
		name = evaluate_admission_event(
			student=self.student.name,
			revision=self._revision() + 7,
			source_event="evt-stale",
			event_type="lifecycle_transition",
			source_reference="L1",
		)
		doc = frappe.get_doc("CRM Admission Event Decision", name)
		self.assertEqual(doc.outcome, "superseded")
		self.assertEqual(doc.reason, "superseded")
		self.assertFalse(doc.run)

	def test_unified_mode_admitted_requests_one_automatic_run(self):
		frappe.conf["crm_admission_event_policy_mode"] = "unified"
		import crm.fcrm.intelligence_runs as intelligence_runs

		original = intelligence_runs.request_automatic_run
		calls = []

		def _fake(domain, target, **kwargs):
			calls.append((domain, target, kwargs))
			return frappe._dict(name="RUN-TEST-1")

		intelligence_runs.request_automatic_run = _fake
		try:
			name = evaluate_admission_event(
				student=self.student.name,
				revision=self._revision(),
				source_event="evt-unified",
				event_type="lifecycle_transition",
				source_reference="L2",
			)
		finally:
			intelligence_runs.request_automatic_run = original

		self.assertEqual(len(calls), 1)
		domain, target, kwargs = calls[0]
		self.assertEqual(domain, "student")
		self.assertEqual(target, self.student.name)
		self.assertEqual(kwargs["admission_event"], "evt-unified")
		self.assertEqual(kwargs["admission_decision"], name)
		self.assertEqual(kwargs["candidate_revision"], self._revision())
		self.assertEqual(kwargs["policy_revision"], POLICY_VERSION)
		self.assertEqual(frappe.db.get_value("CRM Admission Event Decision", name, "run"), "RUN-TEST-1")

	def test_invalid_policy_mode_fails_closed(self):
		frappe.conf["crm_admission_event_policy_mode"] = "bogus"
		with self.assertRaises(frappe.ValidationError):
			evaluate_admission_event(
				student=self.student.name,
				revision=self._revision(),
				source_event="evt-badmode",
				event_type="interaction",
				source_reference="X",
			)
		# The mode is validated before any write, so no decision leaks out.
		self.assertEqual(self._decisions(), [])

	def test_missing_identifiers_are_a_noop(self):
		self.assertEqual(
			evaluate_admission_event(
				student="", revision=1, source_event="x", event_type="interaction"
			),
			"",
		)
		self.assertEqual(
			evaluate_admission_event(
				student=self.student.name, revision=1, source_event="", event_type="interaction"
			),
			"",
		)
		self.assertEqual(self._decisions(), [])

	def test_unknown_student_records_no_decision(self):
		self.assertEqual(
			evaluate_admission_event(
				student="CRM-STUDENT-DOES-NOT-EXIST",
				revision=1,
				source_event="evt-ghost",
				event_type="interaction",
				source_reference="X",
			),
			"",
		)

	# ------------------------------------------------------------ hook guards

	def test_admit_intent_ignores_a_non_material_resave(self):
		fields = dict(
			name="INT-STABLE",
			student=self.student.name,
			intent_type="scholarship",
			intent_role="parent",
			polarity="Positive",
			confidence=0.8,
		)
		doc = _StubDoc(_is_new=False, _before=_StubDoc(**fields), **fields)
		admit_intent(doc)
		self.assertEqual(self._decisions(), [])

	def test_admit_intent_records_one_decision_for_a_material_change(self):
		before = _StubDoc(
			name="INT-MOVED",
			student=self.student.name,
			intent_type="scholarship",
			intent_role="parent",
			polarity="Negative",
			confidence=0.8,
		)
		doc = _StubDoc(
			_is_new=False,
			_before=before,
			name="INT-MOVED",
			student=self.student.name,
			intent_type="scholarship",
			intent_role="parent",
			polarity="Positive",
			confidence=0.8,
		)
		admit_intent(doc)
		admit_intent(doc)  # replay must not double-count

		decisions = self._decisions()
		self.assertEqual(len(decisions), 1)
		self.assertEqual(decisions[0].event_type, "intent")
		self.assertEqual(decisions[0].outcome, "admitted")

	def test_admit_interaction_requires_a_verified_or_outcome_signal(self):
		doc = _StubDoc(name="INT-BLANK", student=self.student.name)
		admit_interaction(doc)
		self.assertEqual(self._decisions(), [])
