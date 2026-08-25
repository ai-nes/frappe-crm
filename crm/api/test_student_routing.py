"""Frappe-backed routing command checks (run with ``bench run-tests``)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_routing import _select_member, process_pending_routing_requests


class TestStudentRouting(FrappeTestCase):
	def test_round_robin_selection_advances_after_cursor(self):
		members = [{"staff": "STAFF-1"}, {"staff": "STAFF-2"}, {"staff": "STAFF-3"}]
		self.assertEqual(_select_member(members, None)["staff"], "STAFF-1")
		self.assertEqual(_select_member(members, "STAFF-1")["staff"], "STAFF-2")
		self.assertEqual(_select_member(members, "STAFF-3")["staff"], "STAFF-1")

	def test_disabled_worker_does_not_mutate_requests(self):
		previous = frappe.conf.pop("crm_student_routing_enabled", None)
		try:
			self.assertEqual(process_pending_routing_requests(), {"processed": 0, "failed": 0, "disabled": 1})
		finally:
			if previous is not None:
				frappe.conf.crm_student_routing_enabled = previous
