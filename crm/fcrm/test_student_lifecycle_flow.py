"""Lifecycle command-flow invariants that are safe to run in a Frappe bench."""

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_lifecycle import StudentLifecycleError, validate_transition


class TestStudentLifecycleFlow(FrappeTestCase):
	def setUp(self):
		self.capabilities = {"lifecycle.transition", "lifecycle.lost", "lifecycle.reopen"}
		self.evidence = [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": "OUT-1"},
			{"category": "intent", "doctype": "CRM Intent", "name": "INT-1"},
			{"category": "document", "doctype": "CRM Student Document", "name": "DOC-1"},
		]

	def test_direct_progression_covers_every_admissions_target(self):
		for target in ("MQL", "Applicant", "Enrolled"):
			self.assertEqual(
				validate_transition("Lead", target, outcome_code="qualified", evidence=self.evidence, capabilities=self.capabilities)["to_stage"], target
			)

	def test_backward_direct_field_like_edge_is_rejected(self):
		with self.assertRaises(StudentLifecycleError) as error:
			validate_transition("Applicant", "MQL", outcome_code="qualified", evidence=self.evidence, capabilities=self.capabilities)
		self.assertEqual(error.exception.code, "INVALID_EDGE")

	def test_reopen_is_only_available_after_lost_and_with_reason(self):
		with self.assertRaises(StudentLifecycleError) as error:
			validate_transition("Lead", "Reopen", reason="Retry", capabilities=self.capabilities)
		self.assertEqual(error.exception.code, "INVALID_EDGE")
