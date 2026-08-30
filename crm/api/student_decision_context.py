"""Least-privilege, bounded Decision Context projection for crm-agents v2."""

from __future__ import annotations

from datetime import timedelta

import frappe

from crm.fcrm.interaction_semantics import resolve_interaction_type
from crm.fcrm.scoring_policy import get_active_policy
from crm.services.sales_action_policy import allowed_generation_actions
from crm.services.student_context import snapshot_hash
from crm.services.student_next_task_policy import choose_next_task_policy

_STUDENT_FIELDS = [
	"name",
	"enrollment_status",
	"lifecycle_stage",
	"major",
	"current_grade",
	"study_stage",
	"branch",
	"province",
	"ward",
	"high_school",
	"assessment_status",
	"assessment_revision",
	"interest_level",
	"fit_level",
	"primary_barrier",
	"latest_score",
	"student_context_revision",
	"sla_evidence_state",
	"sla_evidence_observed_at",
	"score_input_revision",
	"applied_score_input_revision",
	"applied_policy_revision",
]


def _require_agent_identity():
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			"This endpoint is restricted to the crm-agents service identity.", frappe.PermissionError
		)


def _intent_provenance(intent: dict, student: str) -> dict:
	"""Bounded source-interaction reference for the dominant CRM Intent row.

	`interaction` is `reqd=1` on CRM Intent (crm_intent.json) for every new
	row, so a null value here can only mean a pre-existing row saved before
	that constraint existed — represent that explicitly as "legacy_missing"
	rather than fabricating a reference or silently omitting provenance.
	"""
	if not intent:
		return {"state": "none", "interaction": None}
	interaction_name = intent.get("interaction")
	if not interaction_name:
		return {"state": "legacy_missing", "interaction": None}
	source = frappe.db.get_value(
		"CRM Interaction",
		{"name": interaction_name, "student": student},
		["interaction_type", "interaction_datetime"],
		as_dict=True,
	)
	if not source:
		# The link is set but its target CRM Interaction row is gone (deleted,
		# never existed, or — on dirty data — belongs to a different student,
		# which must never be exposed as this student's evidence) — distinct
		# from a genuinely absent link.
		return {"state": "stale_reference", "interaction": None}
	canonical = resolve_interaction_type(source.interaction_type)
	return {
		"state": "linked",
		"interaction": {
			"id": interaction_name,
			"channel": canonical["channel"] if canonical else None,
			"purpose": canonical["purpose"] if canonical else None,
			"disposition": canonical["disposition"] if canonical else None,
			"at": source.interaction_datetime,
		},
	}


def _score_projection(row: dict) -> dict:
	"""Additive score evidence: `freshness` mirrors the same
	(score_input_revision, policy_revision) tuple ordering
	`append_score_if_current` already uses for its CAS write, so a consumer
	never needs to duplicate that comparison logic to know whether the
	last-written score reflects the student's current facts and policy.
	`required_revision` is always None today -- no Recommendation/RCM rule yet
	declares "fresh score mandatory"; it is reserved so a future rule can
	populate it without another contract change.
	"""
	policy = get_active_policy() or {}
	policy_revision = int(policy.get("policy_revision") or 0)
	policy_hash = policy.get("policy_hash") or ""
	current_revision = int(row.get("score_input_revision") or 0)
	applied_input_revision = int(row.get("applied_score_input_revision") or 0)
	applied_policy_revision = int(row.get("applied_policy_revision") or 0)
	if row.get("latest_score") is None:
		freshness = "unknown"
	elif (applied_input_revision, applied_policy_revision) >= (current_revision, policy_revision):
		freshness = "current"
	else:
		freshness = "pending"
	return {
		"current": row.get("latest_score"),
		"freshness": freshness,
		"current_revision": current_revision,
		"required_revision": None,
		"policy_revision": policy_revision,
		"policy_hash": policy_hash,
	}


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
			["intent_type", "importance", "confidence", "polarity", "interaction"],
			order_by="creation desc",
			as_dict=True,
		)
		or {}
	)
	intent_provenance = _intent_provenance(intent, student)
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
		"study": {
			"current_grade": row.current_grade,
			"stage": row.study_stage,
			"high_school": row.high_school,
			"province": row.province,
			"ward": row.ward,
		},
		"assessment": {
			"status": row.assessment_status,
			"revision": int(row.assessment_revision or 0),
			"interest": row.interest_level,
			"fit": row.fit_level,
			"primary_barrier": row.primary_barrier,
		},
		"intent": {
			"type": intent.get("intent_type"),
			"importance": intent.get("importance"),
			"confidence": intent.get("confidence"),
			"polarity": intent.get("polarity"),
			"provenance": intent_provenance,
		},
		"score": _score_projection(row),
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
		f"score-input:revision:{context['score']['current_revision']}:score",
	]
	if action == "PARENT_CONTACT":
		context["evidence_refs"].append(f"student-context:revision:{revision}:parent-authority")
	hash_input = {key: value for key, value in context.items() if key not in {"student_id"}}
	context["snapshot_hash"] = snapshot_hash(hash_input)
	return context


@frappe.whitelist()
def get_student_decision_context(student: str, minimum_revision: int = 0, rollout_epoch: int = 0) -> dict:
	_require_agent_identity()
	return _projection(student, int(minimum_revision))


@frappe.whitelist()
def get_execution_personalization_context(task: str, action: str | None = None) -> dict:
	"""Separate accepted-task context; never usable for task selection."""
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	task_row = frappe.db.get_value(
		"CRM Action",
		task,
		["name", "student", "state", "action_type", "action_revision", "execution_package_version"],
		as_dict=True,
	)
	if not task_row or task_row.state not in {"accepted", "in-progress", "requires-review"}:
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
