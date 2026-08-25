"""Frappe-backed SLA lifecycle checks (run with ``bench run-tests``)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_sla import MEANINGFUL_OUTCOMES, process_due_sla_attempts


class TestStudentSLA(FrappeTestCase):
	def test_only_meaningful_outcomes_can_satisfy_response(self):
		self.assertIn("Resolved", MEANINGFUL_OUTCOMES)
		self.assertNotIn("No Response", MEANINGFUL_OUTCOMES)

	def test_disabled_due_worker_is_a_safe_pause(self):
		previous = frappe.conf.pop("crm_student_sla_enabled", None)
		try:
			self.assertEqual(process_due_sla_attempts(), {"processed": 0, "failed": 0, "disabled": 1})
		finally:
			if previous is not None:
				frappe.conf.crm_student_sla_enabled = previous
