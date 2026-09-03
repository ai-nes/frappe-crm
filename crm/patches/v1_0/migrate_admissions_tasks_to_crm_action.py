"""One-time migration of deterministically admissions-linked generic Tasks."""
import hashlib

import frappe

from crm.fcrm.action_type_catalog import action_category, canonicalize_action_type


_STATUS = {"Backlog": "pending", "Todo": "accepted", "In Progress": "in-progress", "Done": "completed", "Canceled": "cancelled"}
_TYPE = {"call": "CALL", "email": "EMAIL", "message": "MESSAGE", "meeting": "MEETING"}


def execute():
	if not frappe.db.table_exists("CRM Action Item") or not frappe.db.table_exists("Task"):
		return
	frappe.reload_doc("fcrm", "doctype", "crm_action_item")
	for row in frappe.get_all("Task", fields="*"):
		student = row.get("student")
		reference_doctype = row.get("reference_doctype")
		reference_docname = row.get("reference_docname")
		if not student and reference_doctype == "CRM Student":
			student = reference_docname
		if not student and reference_doctype == "CRM Contact" and reference_docname:
			student = frappe.db.get_value("CRM Contact", reference_docname, "student")
		if not student or not frappe.db.exists("CRM Student", student):
			# Non-admissions Tasks are intentionally retained untouched.
			continue
		if frappe.db.exists("CRM Action Item", {"legacy_generic_task": row.name}):
			continue
		staff = frappe.db.get_value("CRM Staff", {"user": row.get("assigned_to")}, "name") if row.get("assigned_to") else None
		priority = str(row.get("priority") or "Medium").lower()
		status = _STATUS.get(row.get("status"), "pending")
		action_code = canonicalize_action_type(_TYPE.get(str(row.get("title") or "").split(" ", 1)[0].lower()))
		doc = frappe.get_doc({"doctype": "CRM Action Item", "legacy_generic_task": row.name, "student": student, "contact": reference_docname if reference_doctype == "CRM Contact" else frappe.db.get_value("CRM Contact", {"student": student}, "name"), "origin": "manual", "action": action_code, "action_type": action_category(action_code), "objective": str(row.get("description") or row.get("title") or "Migrated admissions action")[:500], "disposition": "ACT" if action_code else "MONITOR", "state": status, "execution_status": "completed" if status == "completed" else "planned", "priority": priority if priority in {"high", "medium", "low"} else "medium", "due_at": row.get("due_date"), "action_owner": staff, "source_context_revision": int(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0), "policy_context_version": "task-cutover-v1", "generation_idempotency_key": f"generic-task:{row.name}", "producer_identity": "frappe:migration", "payload_digest": hashlib.sha256(row.name.encode()).hexdigest(), "created_at": row.get("creation"), "completed_at": row.get("modified") if status == "completed" else None, "action_revision": 1, "decision_revision": 1})
		doc.flags.crm_action_command = True
		doc.insert(ignore_permissions=True)
