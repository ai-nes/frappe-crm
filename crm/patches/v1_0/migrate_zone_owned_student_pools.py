"""Idempotently align unrouted pool-owned Students with current Zone pools."""

import frappe

from crm.fcrm.student_assignment import resolve_student_zone, zone_team_pool
from crm.fcrm.student_ownership import change_student_ownership


def execute():
	for student in frappe.get_all(
		"CRM Lead",
		filters={"owner_staff": ["is", "not set"], "owning_pool": ["is", "set"]},
		fields=["name", "branch", "owning_pool", "ownership_revision"],
		limit_page_length=0,
	):
		doc = frappe.get_doc("CRM Lead", student.name)
		geo = resolve_student_zone(doc)
		mapping = zone_team_pool(geo.get("zone"), doc.branch) if geo.get("zone") else None
		if not mapping or mapping.get("pool") == doc.owning_pool:
			continue
		change_student_ownership(
			student=doc.name,
			target_kind="pool",
			target_id=mapping["pool"],
			target_team_id=None,
			reason="Zone-aware pool migration",
			idempotency_key=f"zone-migration:{doc.name}:{doc.ownership_revision}",
			expected_revision=int(doc.ownership_revision or 0),
			correlation_id=f"zone-migration:{doc.name}",
			_internal_service=True,
			_commit=False,
		)
	frappe.db.commit()
