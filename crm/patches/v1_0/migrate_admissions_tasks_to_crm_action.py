"""One-time migration of deterministically admissions-linked generic Tasks."""
import hashlib

import frappe


_STATUS = {"Backlog": "pending", "Todo": "accepted", "In Progress": "in-progress", "Done": "completed", "Canceled": "cancelled"}
_TYPE = {"call": "CALL", "email": "EMAIL", "message": "MESSAGE", "meeting": "MEETING"}


def execute():
	if not frappe.db.table_exists("CRM Action") or not frappe.db.table_exists("Task"):
		return
	frappe.reload_doc("fcrm", "doctype", "crm_action")
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
		# Task autoname is autoincrement, so row.name is an int; legacy_generic_task
		# is a Data column. Normalise once and reuse everywhere to keep the re-run
		# guard, the stored value and the digest consistent across DB backends.
		task_id = str(row.name)
		if frappe.db.exists("CRM Action", {"legacy_generic_task": task_id}):
			continue
		staff = frappe.db.get_value("CRM Staff", {"user": row.get("assigned_to")}, "name") if row.get("assigned_to") else None
		priority = str(row.get("priority") or "Medium").lower()
		status = _STATUS.get(row.get("status"), "pending")
		title = str(row.get("title") or "")
		# Derive the channel from the leading verb; tolerate leading whitespace and
		# trailing punctuation ("  Call:", "\tEmail admissions"). Titles with no
		# recognised verb stay unclassified (action_type=None) and are migrated as
		# non-actionable MONITOR items, matching migrate_sales_actions_to_crm_action.
		first_word = next(iter(title.split()), "").strip(":.,-").lower()
		action_type = _TYPE.get(first_word)
		doc = frappe.get_doc({"doctype": "CRM Action", "legacy_generic_task": task_id, "student": student, "contact": reference_docname if reference_doctype == "CRM Contact" else frappe.db.get_value("CRM Contact", {"student": student}, "name"), "origin": "manual", "action_type": action_type, "objective": str(row.get("description") or row.get("title") or "Migrated admissions action")[:500], "disposition": "ACT" if action_type else "MONITOR", "state": status, "execution_status": "completed" if status == "completed" else "planned", "priority": priority if priority in {"high", "medium", "low"} else "medium", "due_at": row.get("due_date"), "action_owner": staff, "source_context_revision": int(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0), "policy_context_version": "task-cutover-v1", "generation_idempotency_key": f"generic-task:{task_id}", "producer_identity": "frappe:migration", "payload_digest": hashlib.sha256(task_id.encode()).hexdigest(), "created_at": row.get("creation"), "completed_at": row.get("modified") if status == "completed" else None, "action_revision": 1, "decision_revision": 1})
		doc.flags.crm_action_command = True
		doc.insert(ignore_permissions=True)
