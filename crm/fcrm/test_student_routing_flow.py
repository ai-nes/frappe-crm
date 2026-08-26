"""Deterministic routing selection contracts; integration fixtures own DB races."""

from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_routing import _select_member


class TestStudentRoutingFlow(FrappeTestCase):
	def test_round_robin_wraps_and_ignores_removed_cursor_member(self):
		members = [{"staff": "SALE-1"}, {"staff": "SALE-2"}]
		self.assertEqual(_select_member(members, "SALE-1")["staff"], "SALE-2")
		self.assertEqual(_select_member(members, "SALE-2")["staff"], "SALE-1")
		self.assertEqual(_select_member(members, "REMOVED")["staff"], "SALE-1")
