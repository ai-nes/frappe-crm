"""Focused release-gate tests; run inside a Frappe site/bench."""

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.fcrm.student_feature_flags import enabled
from crm.fcrm.student_sla import process_due_sla_attempts, process_pending_sla_deliveries
from crm.fcrm.student_routing import process_pending_routing_requests
from crm.patches.v1_0.phase4_prepare_student_routing_sla import classify_student_topology


class TestPhase4ReleaseGates(FrappeTestCase):
	def test_workers_are_safe_when_rollout_is_disabled(self):
		keys = [
			"crm_student_routing_enabled",
			"crm_student_synchronous_routing_enabled",
			"crm_student_sla_enabled",
			"crm_student_delivery_enabled",
			"crm_student_shared_sla_outbox_enabled",
		]
		previous = {key: frappe.conf.get(key) for key in keys}
		try:
			for key in keys:
				frappe.conf.pop(key, None)
			self.assertFalse(enabled("routing"))
			self.assertFalse(enabled("synchronous_routing"))
			self.assertFalse(enabled("sla"))
			self.assertFalse(enabled("delivery"))
			self.assertFalse(enabled("shared_sla_outbox"))
			self.assertEqual(process_pending_routing_requests(), {"processed": 0, "failed": 0, "disabled": 1})
			self.assertEqual(process_due_sla_attempts(), {"processed": 0, "failed": 0, "disabled": 1})
			self.assertEqual(process_pending_sla_deliveries(), {"processed": 0, "failed": 0, "disabled": 1})
		finally:
			for key, value in previous.items():
				if value is not None:
					frappe.conf[key] = value

	def test_invalid_topology_is_a_release_stop(self):
		self.assertEqual(
			classify_student_topology(
				{"owner_staff": "STAFF-1", "owning_pool": "POOL-1", "owning_team": "TEAM-1"},
				[{"name": "POOL-1", "team": "TEAM-1", "campus": "CAMPUS-1", "is_active": 1}],
			),
			"dual_owner_pool",
		)
