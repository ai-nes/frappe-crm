"""Repair assignment audit rows after ownership was committed successfully."""

import frappe
from frappe.utils import getdate, today


def execute() -> None:
	if not frappe.db.exists("DocType", "CRM Lead Assignment Batch Item"):
		return

	parents = set()
	items = frappe.get_all(
		"CRM Lead Assignment Batch Item",
		filters={"status": ["in", ["pending", "failed", "manual_review"]]},
		fields=["name", "parent", "lead", "status"],
		limit_page_length=0,
		ignore_permissions=True,
	)
	for item in items:
		lead = frappe.db.get_value(
			"CRM Lead",
			item.lead,
			["processing_status", "owner_staff", "assigned_to", "owning_team"],
			as_dict=True,
		)
		if not lead or lead.processing_status != "ASSIGNED":
			continue
		owner_staff = lead.owner_staff or lead.assigned_to
		if not owner_staff or not lead.owning_team:
			continue

		active_load = _active_load(owner_staff)
		capacity_limit = _capacity_limit(owner_staff)
		frappe.db.set_value(
			"CRM Lead Assignment Batch Item",
			item.name,
			{
				"status": "assigned",
				"owner_staff": owner_staff,
				"team": lead.owning_team,
				"active_load": active_load,
				"capacity_limit": capacity_limit,
				"remaining_capacity": max(0, capacity_limit - active_load)
				if capacity_limit
				else 0,
			},
			update_modified=False,
		)
		parents.add(item.parent)

	for parent in parents:
		statuses = frappe.get_all(
			"CRM Lead Assignment Batch Item",
			filters={"parent": parent, "parenttype": "CRM Lead Assignment Batch"},
			fields=["status"],
			limit_page_length=0,
			ignore_permissions=True,
		)
		counts = {
			status: sum(row.status == status for row in statuses)
			for status in ("assigned", "deferred", "manual_review", "failed")
		}
		frappe.db.set_value(
			"CRM Lead Assignment Batch",
			parent,
			{
				"total_count": len(statuses),
				"assigned_count": counts["assigned"],
				"deferred_count": counts["deferred"],
				"manual_review_count": counts["manual_review"],
				"failed_count": counts["failed"],
			},
			update_modified=False,
		)


def _active_load(staff: str) -> int:
	row = frappe.db.sql(
		"""
		select count(distinct name)
		from `tabCRM Lead`
		where (owner_staff = %s or assigned_to = %s)
			and coalesce(processing_status, 'NEW') <> 'CLOSED'
			and coalesce(conversion_status, '') <> 'Converted'
			and coalesce(converted_student, '') = ''
		""",
		(staff, staff),
	)[0]
	return int(row[0] or 0)


def _capacity_limit(staff: str) -> int:
	period = frappe.db.get_value(
		"CRM Staff Capacity Period",
		{
			"staff": staff,
			"period_start": ["<=", getdate(today())],
			"period_end": [">=", getdate(today())],
			"approved": 1,
		},
		"max_active_students",
	)
	return int(period or 0)
