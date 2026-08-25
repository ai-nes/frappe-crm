"""Isolated live V2 Student Task rehearsal.

Run only on the explicitly enabled local/staging fixture site:

    bench --site crm.localhost execute crm.demo.student_task_v2_live.run

The synthetic records are intentionally retained as evidence. This harness
does not delete or rewrite historical Recommendation/Sales Action rows.
"""

from __future__ import annotations

import time
from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from crm.demo import seed_demo
from crm.api.student_decision import accept_student_task, record_sales_action_outcome


PREFIX = "LIVE-V2-E2E"


def _wait_for(fetch, *, timeout: int = 90, label: str):
	deadline = time.monotonic() + timeout
	last = None
	while time.monotonic() < deadline:
		# The agents webhook commits in a separate request/transaction. Close
		# this runner's read transaction before every poll so MariaDB's default
		# snapshot isolation cannot hide a newly projected task or re-evaluation.
		frappe.db.commit()
		last = fetch()
		if last:
			return last
		frappe.db.commit()
		time.sleep(2)
	raise RuntimeError(f"{label} did not converge within {timeout}s: {last}")


def _new_student():
	run_id = now_datetime().strftime("%Y%m%d%H%M%S")
	phone = f"09862{int(time.time()) % 100000:05d}"
	student = frappe.get_doc(
		{
			"doctype": "CRM Student",
			"student_name": f"{PREFIX}-{run_id}",
			"email": f"{PREFIX.lower()}-{run_id}@example.test",
			"phone": phone,
			"enrollment_status": "Mới",
			"admission_year": str(now_datetime().year),
		}
	).insert(ignore_permissions=True)
	interaction_type = seed_demo._ensure_interaction_type("Phone Call")
	intent_type = seed_demo._ensure_intent_type("Tuition", "High", f"{PREFIX} tuition")
	interaction = frappe.get_doc(
		{
			"doctype": "CRM Interaction",
			"student": student.name,
			"interaction_type": interaction_type,
			"interaction_datetime": now_datetime() - timedelta(hours=1),
			"outcome": "Captured",
			"summary": f"{PREFIX}: synthetic tuition question",
			"notes": f"{PREFIX}: no real-person data",
		}
	).insert(ignore_permissions=True)
	intent = frappe.get_doc(
		{
			"doctype": "CRM Intent",
			"student": student.name,
			"interaction": interaction.name,
			"intent_type": intent_type,
			"intent_role": "Dominant",
			"polarity": "Positive",
			"confidence": 90,
			"notes": f"{PREFIX}: synthetic intent",
		}
	).insert(ignore_permissions=True)
	frappe.db.commit()
	return student.name, intent.name


def run() -> dict:
	"""Run the real V2 event, task, decision, action, outcome loop."""
	frappe.only_for("System Manager")
	if frappe.conf.get("crm_agents_v2_enabled", 0) in (0, "0", False):
		frappe.throw("crm_agents_v2_enabled must be enabled for the live V2 test.", frappe.PermissionError)

	student, intent = _new_student()
	task = _wait_for(
		lambda: frappe.db.get_value(
			"CRM Student Task",
			{"student": student, "current_slot": "CURRENT"},
			["name", "state", "generation_status", "action_type", "recommendation", "source_context_revision"],
			as_dict=True,
		),
		label="V2 Student Task",
	)
	if task.generation_status != "succeeded" or task.action_type != "CALL" or not task.recommendation:
		raise RuntimeError(f"unexpected V2 task projection: {task}")

	recommendation = frappe.db.get_value(
		"CRM Recommendation",
		task.recommendation,
		["name", "rule_key", "recommended_action", "student"],
		as_dict=True,
	)
	accepted = accept_student_task(task.name, str(frappe.db.get_value("CRM Student Task", task.name, "modified")))
	frappe.db.commit()
	if not accepted.get("sales_action"):
		raise RuntimeError(f"Sales Decision did not create Sales Action: {accepted}")

	action = frappe.db.get_value(
		"CRM Sales Action",
		accepted["sales_action"],
		["name", "student_task", "action_type", "execution_status"],
		as_dict=True,
	)
	if not action or action.student_task != task.name:
		raise RuntimeError(f"Sales Action/task link is invalid: {action}")

	outcome = record_sales_action_outcome(
		action.name,
		str(frappe.db.get_value("CRM Sales Action", action.name, "modified")),
		"INTEREST_INCREASED",
		f"{PREFIX}: synthetic live outcome",
	)
	frappe.db.commit()

	reviewed = _wait_for(
		lambda: (
			row
			if (row := frappe.db.get_value(
				"CRM Student Task",
				task.name,
				["name", "state", "requires_review", "review_revision", "source_context_revision"],
				as_dict=True,
			))
			and row.state == "REQUIRES_REVIEW"
			and int(row.requires_review or 0) == 1
			else None
		),
		label="V2 post-outcome re-evaluation",
	)
	return {
		"status": "passed",
		"student": student,
		"intent": intent,
		"context_revision": task.source_context_revision,
		"recommendation": recommendation,
		"task": {"name": task.name, "state_before": task.state, "action_type": task.action_type},
		"sales_decision": {"status": accepted.get("state"), "task": task.name},
		"sales_action": action,
		"outcome": outcome,
		"re_evaluation": reviewed,
		"historical_evidence_retained": True,
	}
