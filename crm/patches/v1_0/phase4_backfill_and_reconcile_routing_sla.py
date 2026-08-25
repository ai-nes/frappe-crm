"""Create only deterministic routing work; never fabricate historical SLA time."""

from __future__ import annotations

import frappe

from crm.fcrm.student_routing import enqueue_student_routing
from crm.patches.v1_0.phase4_prepare_student_routing_sla import classify_student_topology


def execute():
	students = frappe.get_all(
		"CRM Student",
		fields=["name", "enrollment_status", "lifecycle_stage", "owner_staff", "assigned_to", "owning_team", "owning_pool", "branch"],
		order_by="name asc",
	)
	pools = frappe.get_all("CRM Student Pool", fields=["name", "team", "campus", "is_active"])
	classification = {row.name: classify_student_topology(row, pools) for row in students}
	invalid = {name: state for name, state in classification.items() if state not in {"owner", "pool", "terminal"}}
	queued = []
	for row in students:
		if classification[row.name] != "pool":
			continue
		if frappe.db.exists("CRM Student Routing Request", {"student": row.name, "ownership_revision": row.get("ownership_revision") or 0}):
			continue
		try:
			request = enqueue_student_routing(row.name, trigger="pool_entry")
			queued.append(request.name)
		except Exception:
			invalid[row.name] = "routing_request_failed"
			frappe.db.rollback()
	return {
		"students_checked": len(students),
		"invalid_topology": invalid,
		"routing_requests_created": queued,
		"sla_backfilled": 0,
		"note": "No Contact SLA timestamps, Student creation times, or fabricated response evidence were used.",
	}
