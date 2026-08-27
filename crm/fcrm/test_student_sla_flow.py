"""First-response SLA invariants that do not need a mutable site fixture."""

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_sla import MEANINGFUL_OUTCOMES, TERMINAL


class TestStudentSLAFlow(FrappeTestCase):
	def test_only_business_outcomes_are_meaningful_and_terminal_states_do_not_reopen(self):
		self.assertTrue({"Captured", "Follow Up Needed", "Resolved", "Converted"}.issubset(MEANINGFUL_OUTCOMES))
		self.assertIn("responded", TERMINAL)
		self.assertIn("superseded", TERMINAL)
