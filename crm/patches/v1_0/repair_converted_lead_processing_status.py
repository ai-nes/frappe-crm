"""Align legacy converted Leads with the server-managed processing workflow."""

import frappe


def execute() -> None:
	lead_fields = {field.fieldname for field in frappe.get_meta("CRM Lead").fields}
	required = {"conversion_status", "converted_student", "processing_status", "resolution"}
	if not required.issubset(lead_fields):
		return

	fields = ["name", "resolution", "converted_student"]
	if "matched_student" in lead_fields:
		fields.append("matched_student")
	if "resolution_reason" in lead_fields:
		fields.append("resolution_reason")

	for row in frappe.get_all(
		"CRM Lead",
		filters={"conversion_status": "Converted"},
		fields=fields,
		limit_page_length=0,
		ignore_permissions=True,
	):
		resolution = str(row.get("resolution") or "").strip().upper()
		if resolution not in {"MATCHED", "CREATED"}:
			resolution = "MATCHED" if row.get("matched_student") else "CREATED"
		updates = {
			"processing_status": "CLOSED",
			"resolution": resolution,
		}
		if "resolution_reason" in lead_fields and not row.get("resolution_reason"):
			updates["resolution_reason"] = f"{resolution} handoff completed."
		frappe.db.set_value("CRM Lead", row.name, updates, update_modified=False)

	_repair_assignment_history()


def _repair_assignment_history() -> None:
	if not frappe.db.exists("DocType", "CRM Lead Assignment Batch Item"):
		return

	batch_names = set()
	for item in frappe.get_all(
		"CRM Lead Assignment Batch Item",
		filters={"status": "pending"},
		fields=["name", "parent", "lead"],
		limit_page_length=0,
		ignore_permissions=True,
	):
		lead = frappe.db.get_value(
			"CRM Lead",
			item.lead,
			["processing_status", "owner_staff", "assigned_to"],
			as_dict=True,
		)
		if not lead or lead.processing_status != "ASSIGNED":
			continue
		owner_staff = lead.owner_staff or lead.assigned_to
		if not owner_staff:
			continue
		event = None
		if frappe.db.exists("DocType", "CRM Student Ownership Event"):
			event = frappe.get_all(
				"CRM Student Ownership Event",
				filters={"student": item.lead, "route_trigger": "assignment_batch"},
				fields=["next_owning_team", "reason"],
				order_by="event_at desc, creation desc",
				limit_page_length=1,
				ignore_permissions=True,
			)
			event = event[0] if event else None
		values = {
			"status": "assigned",
			"owner_staff": owner_staff,
		}
		if event and event.get("next_owning_team"):
			values["team"] = event.next_owning_team
		if event and event.get("reason"):
			values["reason"] = event.reason
		frappe.db.set_value("CRM Lead Assignment Batch Item", item.name, values, update_modified=False)
		batch_names.add(item.parent)

	if not frappe.db.exists("DocType", "CRM Lead Assignment Batch"):
		return
	for batch_name in batch_names:
		statuses = frappe.get_all(
			"CRM Lead Assignment Batch Item",
			filters={"parent": batch_name, "parenttype": "CRM Lead Assignment Batch"},
			fields=["status"],
			limit_page_length=0,
			ignore_permissions=True,
		)
		counts = {status: sum(row.status == status for row in statuses) for status in (
			"assigned", "deferred", "manual_review", "failed"
		)}
		frappe.db.set_value(
			"CRM Lead Assignment Batch",
			batch_name,
			{
				"total_count": len(statuses),
				"assigned_count": counts["assigned"],
				"deferred_count": counts["deferred"],
				"manual_review_count": counts["manual_review"],
				"failed_count": counts["failed"],
			},
			update_modified=False,
		)
