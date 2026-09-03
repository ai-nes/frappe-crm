"""Move historical CRM Sales Action rows into the canonical CRM Action.

The old table is treated as an upgrade-time archive.  Fresh installs have no
such table and safely skip this patch.  Re-running is idempotent.
"""

import frappe

from crm.fcrm.action_type_catalog import action_category, canonicalize_action_type


def execute():
	if not frappe.db.table_exists("CRM Sales Action"):
		return {"migrated": 0, "skipped": 0}
	frappe.reload_doc("fcrm", "doctype", "crm_action_item")
	logger = frappe.logger("crm.migrations")
	migrated = skipped = 0
	for row in frappe.get_all("CRM Sales Action", fields="*"):
		if frappe.db.exists("CRM Action Item", {"legacy_sales_action": row.name}):
			continue
		student = row.get("student")
		if not student or not frappe.db.exists("CRM Student", student):
			logger.warning("Skipped legacy CRM Sales Action %s: missing CRM Student", row.name)
			skipped += 1
			continue
		canonical = None
		if row.get("student_task"):
			canonical = frappe.db.get_value("CRM Action Item", {"legacy_student_task": row.student_task}, "name")
		if not canonical and row.get("recommendation"):
			canonical = frappe.db.get_value("CRM Action Item", {"recommendation": row.recommendation}, "name")
		if canonical:
			frappe.db.set_value("CRM Action Item", canonical, {**_mapped_fields(row), **_state_fields(row)}, update_modified=False)
			frappe.db.set_value("CRM Action Item", canonical, "legacy_sales_action", row.name, update_modified=False)
			migrated += 1
			continue
		values = {
			"doctype": "CRM Action Item",
			"legacy_sales_action": row.name,
			"student": student,
			"recommendation": row.get("recommendation"),
			"action": canonicalize_action_type(row.get("action_type")) if row.get("action_type") not in {"WAIT", "FOLLOW_UP"} else None,
			"action_type": action_category(canonicalize_action_type(row.get("action_type"))) if row.get("action_type") not in {"WAIT", "FOLLOW_UP"} else None,
			"objective": f"Migrated historical Sales Action ({row.get('action_type') or 'unknown'})",
			"disposition": "ACT" if row.get("action_type") not in {"WAIT", "FOLLOW_UP"} else "MONITOR",
			"origin": "system",
			"source_context_revision": 0,
			"policy_context_version": "migration:sales-action",
			"generation_idempotency_key": f"migration:sales-action:{row.name}",
			"producer_identity": "frappe:migration",
			"payload_digest": "0" * 64,
			"action_revision": row.get("action_revision") or 1,
			"created_at": row.get("created_at") or row.get("creation"),
		}
		for key, value in _mapped_fields(row).items():
			if value not in (None, ""):
				values[key] = value
		values.update(_state_fields(row))
		frappe.get_doc(values).insert(ignore_permissions=True)
		migrated += 1
	return {"migrated": migrated, "skipped": skipped}


def _state(status):
	return {"planned": "accepted", "in_progress": "in-progress", "completed": "completed", "failed": "requires-review", "cancelled": "cancelled"}.get(status, "accepted")


def _state_fields(row):
	status = row.get("execution_status") or "planned"
	state = _state(status)
	fields = {"state": state, "execution_status": status}
	if state in {"completed", "cancelled", "rejected", "superseded"}:
		# A terminal Action never keeps the student's single current slot.
		fields["current_slot"] = None
	return fields


def _mapped_fields(row):
	return {
		"due_at": row.get("due_at"),
		"action_owner": row.get("assignee_staff"),
		"execution_status": row.get("execution_status") or "planned",
		"started_at": row.get("started_at"),
		"completed_at": row.get("completed_at"),
		"outcome_code": row.get("outcome_code") or row.get("business_outcome"),
		"outcome_notes": row.get("outcome_notes"),
		"outcome_evidence": row.get("outcome_evidence"),
		"linked_interaction": row.get("linked_interaction"),
		"terminal_reason": row.get("terminal_reason"),
	}
