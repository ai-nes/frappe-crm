"""Classify legacy routing topology; never create technical queue rows."""

from __future__ import annotations

import frappe
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
	return {
		"students_checked": len(students),
		"invalid_topology": invalid,
		"routing_requests_created": [],
		"sla_backfilled": 0,
		"note": "No routing request, Contact SLA timestamp, or fabricated response evidence was created.",
	}
