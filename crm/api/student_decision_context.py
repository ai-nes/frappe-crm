"""Least-privilege, bounded Decision Context projection for crm-agents v2."""

from __future__ import annotations

from datetime import timedelta

import frappe

from crm.services.sales_action_policy import allowed_generation_actions
from crm.services.student_context import snapshot_hash
from crm.services.student_next_task_policy import choose_next_task_policy

_STUDENT_FIELDS = [
	"name",
	"enrollment_status",
	"lifecycle_stage",
	"major",
	"branch",
	"province",
	"latest_score",
	"student_context_revision",
	"sla_evidence_state",
	"sla_evidence_observed_at",
]


def _require_agent_identity():
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			"This endpoint is restricted to the crm-agents service identity.", frappe.PermissionError
		)


def _projection(student: str, minimum_revision: int) -> dict:
	row = frappe.db.get_value("CRM Student", student, _STUDENT_FIELDS, as_dict=True)
	if not row:
		frappe.throw("Student not found.", frappe.DoesNotExistError)
	if not frappe.has_permission("CRM Student", "read", student, throw=False):
		frappe.throw("Student projection is not authorized.", frappe.PermissionError)
	revision = int(row.student_context_revision or 0)
	if revision < int(minimum_revision):
		frappe.throw("Requested Student revision is not available.", frappe.ValidationError)
	intent = (
		frappe.db.get_value(
			"CRM Intent",
			{"student": student},
			["intent_type", "importance", "confidence"],
			order_by="creation desc",
			as_dict=True,
		)
		or {}
	)
	interaction = (
		frappe.db.get_value(
			"CRM Interaction",
			{"student": student},
			["interaction_type", "outcome", "interaction_datetime"],
			order_by="interaction_datetime desc",
			as_dict=True,
		)
		or {}
	)
	sla_state = row.sla_evidence_state or "unknown"
	if (
		row.sla_evidence_observed_at
		and row.sla_evidence_observed_at < frappe.utils.now_datetime() - timedelta(minutes=5)
	):
		sla_state = "stale"
	# Do not add names, phones, emails, raw notes, or free text to this DTO.
	context = {
		"student_id": student,
		"returned_revision": revision,
		"policy_version": "student-next-task-v2",
		"eligibility": {"student": True},
		"lifecycle": {
			"stage": row.lifecycle_stage or row.enrollment_status,
		},
		"intent": {
			"type": intent.get("intent_type"),
			"importance": intent.get("importance"),
			"confidence": intent.get("confidence"),
		},
		"score": {"current": row.latest_score},
		"interaction": {
			"channel": interaction.get("interaction_type"),
			"outcome": interaction.get("outcome"),
			"at": interaction.get("interaction_datetime"),
		},
		"sla_evidence": {
			"state": sla_state,
			"observed_at": row.sla_evidence_observed_at,
		},
		"allowed_action_types": allowed_generation_actions(student),
		"evidence_refs": [],
	}
	allowed_actions = context["allowed_action_types"]
	stage = context["lifecycle"]["stage"]
	eligible = str(stage or "").casefold() not in {"lost", "enrolled", "đã xác nhận", "closed"}
	action, objective, actionable = choose_next_task_policy(
		intent.get("intent_type"),
		stage,
		allowed_actions,
		eligible=eligible,
		parent_authorized="PARENT_CONTACT" in allowed_actions,
	)
	context["eligibility"]["student"] = eligible
	context["eligibility"]["actionable"] = actionable
	context["lifecycle"].update({"next_task_action": action, "next_task_objective": objective})
	context["evidence_refs"] = [
		f"student-context:revision:{revision}:intent",
		f"student-context:revision:{revision}:stage",
	]
	if action == "PARENT_CONTACT":
		context["evidence_refs"].append(f"student-context:revision:{revision}:parent-authority")
	hash_input = {key: value for key, value in context.items() if key not in {"student_id"}}
	context["snapshot_hash"] = snapshot_hash(hash_input)
	return context


@frappe.whitelist()
def get_student_decision_context(student: str, minimum_revision: int = 0, rollout_epoch: int = 0) -> dict:
	_require_agent_identity()
	if frappe.conf.get("crm_agents_v2_enabled", 0) in (0, "0", False):
		frappe.throw("Student task v2 is disabled.", frappe.PermissionError)
	return _projection(student, int(minimum_revision))


@frappe.whitelist()
def get_execution_personalization_context(task: str, action: str | None = None) -> dict:
	"""Separate accepted-task context; never usable for task selection."""
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	task_row = frappe.db.get_value(
		"CRM Student Task",
		task,
		["name", "student", "state", "action_type", "action_revision", "execution_package_version"],
		as_dict=True,
	)
	if not task_row or task_row.state not in {"ACCEPTED", "IN_PROGRESS", "REQUIRES_REVIEW"}:
		frappe.throw("Execution context requires an accepted task.", frappe.ValidationError)
	if not frappe.has_permission("CRM Student", "read", task_row.student, throw=False):
		frappe.throw("Task is outside the actor's Student scope.", frappe.PermissionError)
	return {
		"task": task_row.name,
		"student": task_row.student,
		"action_type": task_row.action_type,
		"action_revision": task_row.action_revision,
		"package_revision": task_row.execution_package_version,
		"recipient": {"source": "Frappe command authorization"},
		"evidence_refs": [],
	}
