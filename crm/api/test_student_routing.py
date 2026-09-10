"""Frappe-backed routing command checks (run with ``bench run-tests``)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_routing import (
	MANUAL_QUEUE,
	_routing_context,
	_select_member,
	process_pending_routing_requests,
	repair_orphan_routing_requests,
	route_pool_owned_student,
)


class TestStudentRouting(FrappeTestCase):
	def test_province_only_lead_stays_in_province_queue(self):
		with (
			patch(
				"crm.fcrm.student_routing.resolve_student_zone",
				return_value={"tier": 3, "reason": "province"},
			),
			patch.object(frappe.db, "exists") as exists,
		):
			result = _routing_context({"province": "HCM"}, {"team": "TEAM-1"})

		self.assertEqual(result, {"tier": 3, "queue": MANUAL_QUEUE})
		exists.assert_not_called()

	def test_round_robin_selection_advances_after_cursor(self):
		members = [{"staff": "STAFF-1"}, {"staff": "STAFF-2"}, {"staff": "STAFF-3"}]
		self.assertEqual(_select_member(members, None)["staff"], "STAFF-1")
		self.assertEqual(_select_member(members, "STAFF-1")["staff"], "STAFF-2")
		self.assertEqual(_select_member(members, "STAFF-3")["staff"], "STAFF-1")

	def test_disabled_worker_does_not_mutate_requests(self):
		previous = frappe.conf.pop("crm_student_routing_enabled", None)
		try:
			with patch.object(frappe.db, "get_single_value", return_value=None):
				self.assertEqual(
					process_pending_routing_requests(), {"processed": 0, "failed": 0, "disabled": 1}
				)
		finally:
			if previous is not None:
				frappe.conf.crm_student_routing_enabled = previous

	def test_missing_policy_defers_without_selecting_member_or_changing_owner(self):
		student = {"name": "STU-1", "ownership_revision": 4}
		with (
			patch("crm.fcrm.student_routing.enabled", return_value=True),
			patch("crm.fcrm.student_routing.frappe.db.sql"),
			patch("crm.fcrm.student_routing.frappe.get_doc", return_value=student),
			patch("crm.fcrm.student_routing._canonical_pool", return_value={"name": "POOL-1"}),
			patch(
				"crm.fcrm.student_routing._routing_context",
				return_value={
					"tier": 2,
					"zone": "ZONE-1",
					"mapping": {"pool": "POOL-1", "team": "TEAM-1"},
				},
			),
			patch("crm.fcrm.student_routing._active_policy", return_value=None),
			patch("crm.fcrm.student_routing._eligible_members") as members,
		):
			result = route_pool_owned_student("STU-1", expected_revision=4)
		self.assertEqual(result, {"status": "deferred", "reason": "NO_ACTIVE_POLICY", "student": "STU-1"})
		members.assert_not_called()

	def test_stale_revision_is_a_noop_before_pool_or_policy_lookup(self):
		student = {"name": "STU-2", "ownership_revision": 5}
		with (
			patch("crm.fcrm.student_routing.enabled", return_value=True),
			patch("crm.fcrm.student_routing.frappe.db.sql"),
			patch("crm.fcrm.student_routing.frappe.get_doc", return_value=student),
			patch("crm.fcrm.student_routing._canonical_pool") as pool,
		):
			result = route_pool_owned_student("STU-2", expected_revision=4)
		self.assertEqual(result["status"], "superseded")
		self.assertEqual(result["reason"], "STALE_OWNERSHIP_REVISION")
		pool.assert_not_called()

	def test_orphan_routing_requests_are_failed_without_deleting_audit_rows(self):
		with (
			patch(
				"crm.fcrm.student_routing.frappe.get_all",
				return_value=[
					{"name": "route:missing:0", "student": "ENR-MISSING", "status": "pending", "revision": 2}
				],
			),
			patch("crm.fcrm.student_routing.frappe.db.exists", return_value=False),
			patch("crm.fcrm.student_routing.frappe.db.set_value") as set_value,
		):
			result = repair_orphan_routing_requests()

		self.assertEqual(result, {"checked": 1, "repaired": 1})
		set_value.assert_called_once()
		values = set_value.call_args.args[2]
		self.assertEqual(values["status"], "failed")
		self.assertEqual(values["revision"], 3)
		self.assertEqual(values["last_error_code"], "STUDENT_NOT_FOUND")
