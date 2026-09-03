"""Backfill the canonical CRM Action from every legacy Student Task."""
import frappe

from crm.fcrm.action_type_catalog import action_category, canonicalize_action_type


def execute():
	frappe.reload_doc("fcrm", "doctype", "crm_action_item")
	if not frappe.db.table_exists("CRM Student Task"):
		return
	logger = frappe.logger("crm.migrations")
	link_targets = {
		"recommendation": "CRM Recommendation",
		"action_owner": "CRM Staff",
		"decision_actor": "User",
	}
	for row in frappe.get_all("CRM Student Task", fields="*"):
		if frappe.db.exists("CRM Action Item", {"legacy_student_task": row.name}):
			continue
		student = row.get("student")
		if not student or not frappe.db.exists("CRM Student", student):
			logger.warning("Skipped legacy CRM Student Task %s: missing CRM Student", row.name)
			continue
		values = {"doctype": "CRM Action Item", "legacy_student_task": row.name}
		for target, source in {
			"student":"student", "recommendation":"recommendation", "objective":"objective", "disposition":"disposition",
			"source_context_revision":"source_context_revision", "policy_context_version":"context_version",
			"generation_idempotency_key":"generation_idempotency_key", "producer_identity":"producer_identity",
			"payload_digest":"payload_digest", "evidence_references":"evidence_references", "package_seed":"package_seed",
			"priority":"priority", "worklist_priority_rank":"worklist_priority_rank", "revisit_at":"revisit_at", "action_owner":"assigned_to",
			"current_slot":"current_slot", "requires_review":"requires_review", "review_revision":"review_revision",
			"action_revision":"action_revision", "execution_package_version":"execution_package_version",
			"terminal_reason":"decision_reason", "created_at":"created_at", "accepted_at":"accepted_at",
			"completed_at":"completed_at", "decision_reason":"decision_reason", "decision_actor":"decision_actor",
			"decision_at":"decision_at", "decision_revision":"decision_revision",
		}.items():
			value = row.get(source)
			if target in link_targets and value and not frappe.db.exists(link_targets[target], value):
				continue
			if value is not None:
				values[target] = row.get(source)
		action_code = canonicalize_action_type(row.get("action_type"))
		if action_category(action_code):
			values["action"] = action_code
			values["action_type"] = action_category(action_code)
		values["state"] = {"PENDING":"pending", "ACCEPTED":"accepted", "IN_PROGRESS":"in-progress", "REQUIRES_REVIEW":"requires-review", "COMPLETED":"completed", "CANCELLED":"cancelled", "SUPERSEDED":"superseded", "REJECTED":"rejected", "DEFERRED":"deferred"}.get(row.state, "pending")
		frappe.get_doc(values).insert(ignore_permissions=True)
