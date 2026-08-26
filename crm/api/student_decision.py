"""Thin HTTP adapters for Phase 6 decision commands."""
from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.student_decision import (
	StudentDecisionError,
	decide_recommendation as _decide_recommendation,
	decide_student_task as _decide_student_task,
	reassign_sales_action as _reassign_sales_action,
	transition_sales_action as _transition_sales_action,
)


def _require_v2_service():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			_("This command is restricted to the crm-agents service identity."), frappe.PermissionError
		)


def _task_result(task, *, idempotent=False):
	return {
		"name": task.name,
		"student": task.student,
		"state": task.state,
		"disposition": task.disposition,
		"action_type": task.action_type,
		"generation_status": task.generation_status,
		"generation_failed_at": str(task.generation_failed_at) if task.generation_failed_at else None,
		"source_context_revision": task.source_context_revision,
		"task_revision": str(task.modified),
		"recommendation": task.recommendation,
		"sales_action": task.sales_action,
		"idempotent": idempotent,
	}


@frappe.whitelist()
def upsert_student_next_task(
	student: str,
	expected_context_revision: int,
	generation_idempotency_key: str,
	producer_identity: str,
	payload_digest: str,
	rollout_epoch: int,
	candidate: dict | str,
) -> dict:
	"""Only mutation endpoint for v2 generation; compare-and-swap + idempotency."""
	_require_v2_service()
	if isinstance(candidate, str):
		candidate = frappe.parse_json(candidate)
	if not isinstance(candidate, dict):
		frappe.throw(_("Candidate must be an object."), frappe.ValidationError)
	canonical = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
	if hashlib.sha256(canonical.encode()).hexdigest() != payload_digest:
		frappe.throw(_("Candidate payload digest does not match."), frappe.ValidationError)
	if int(expected_context_revision) < 0 or int(rollout_epoch) < 0:
		frappe.throw(_("Invalid revision."), frappe.ValidationError)
	if frappe.conf.get("crm_agents_v2_rollout_epoch") is not None and int(
		frappe.conf.get("crm_agents_v2_rollout_epoch", 0)
	) != int(rollout_epoch):
		frappe.throw(_("Stale rollout epoch."), frappe.ValidationError)
	action_type = candidate.get("action_type")
	disposition = candidate.get("disposition")
	if int(candidate.get("context_revision", -1)) != int(expected_context_revision):
		frappe.throw(_("Candidate revision does not match expected context revision."), frappe.ValidationError)
	if disposition not in {"ACT", "MONITOR", "NURTURE"} or (disposition == "ACT") != bool(action_type):
		frappe.throw(_("Invalid v2 disposition/action combination."), frappe.ValidationError)
	row = frappe.db.sql(
		"SELECT name, student_context_revision FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Student not found."), frappe.DoesNotExistError)
	existing = frappe.db.get_value(
		"CRM Student Task",
		{
			"producer_identity": producer_identity,
			"student": student,
			"generation_idempotency_key": generation_idempotency_key,
		},
		["name", "payload_digest"],
		as_dict=True,
	)
	if existing:
		if existing.payload_digest != payload_digest:
			frappe.throw(_("Generation idempotency key was reused with a different payload."), frappe.ValidationError)
		return _task_result(frappe.get_doc("CRM Student Task", existing.name), idempotent=True)
	current_revision = int(row[0].student_context_revision or 0)
	if current_revision != int(expected_context_revision):
		frappe.throw(_("Student context changed; retry from the newer projection."), frappe.ValidationError)
	current = frappe.db.sql(
		"SELECT name, state FROM `tabCRM Student Task` WHERE student = %s AND current_slot = 'CURRENT' FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if current:
		from crm.services.student_context import is_committed_task_state

		if is_committed_task_state(current[0].state):
			task = frappe.get_doc("CRM Student Task", current[0].name)
			task.requires_review = 1
			task.review_revision = current_revision
			task.state = "REQUIRES_REVIEW"
			frappe.flags.student_task_command = True
			try:
				task.save(ignore_permissions=True)
			finally:
				frappe.flags.student_task_command = False
			return _task_result(task)
		frappe.db.set_value(
			"CRM Student Task",
			current[0].name,
			{"current_slot": None, "state": "SUPERSEDED"},
			update_modified=False,
		)
	from crm.services.sales_action_policy import V2_ACTION_TYPES

	if action_type and action_type not in V2_ACTION_TYPES:
		frappe.throw(_("Unsupported v2 action type."), frappe.ValidationError)
	task = frappe.get_doc(
		{
			"doctype": "CRM Student Task",
			"student": student,
			"current_slot": "CURRENT",
			"source_context_revision": current_revision,
			"disposition": disposition,
			"action_type": action_type,
			"objective": str(candidate.get("objective") or "")[:500],
			"policy_version": candidate.get("policy_version"),
			"context_version": candidate.get("snapshot_hash"),
			"state": "PENDING",
			"generation_status": "succeeded",
			"requires_review": 0,
			"action_revision": 1 if action_type else 0,
			"execution_package_version": 1 if action_type else 0,
			"generation_idempotency_key": generation_idempotency_key,
			"producer_identity": producer_identity,
			"payload_digest": payload_digest,
			"evidence_references": json.dumps(candidate.get("evidence_refs", []), separators=(",", ":")),
			"package_seed": json.dumps(candidate.get("package_seed") or {}, separators=(",", ":")),
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	return _task_result(task)


@frappe.whitelist()
def record_student_task_generation_failure(
	student: str, source_revision: int, reason: str, rollout_epoch: int = 0
) -> dict:
	"""Persist an explicit bounded failure for the convergence SLO."""
	_require_v2_service()
	row = frappe.db.sql(
		"SELECT name, student_context_revision FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row or int(row[0].student_context_revision or 0) != int(source_revision):
		return {"status": "deferred", "reason": "revision_moved"}
	current = frappe.db.get_value("CRM Student Task", {"student": student, "current_slot": "CURRENT"}, "name")
	if current:
		frappe.db.set_value(
			"CRM Student Task",
			current,
			{
				"generation_status": "failed",
				"generation_failed_at": frappe.utils.now_datetime(),
				"generation_failure_reason": str(reason)[:500],
			},
			update_modified=False,
		)
		return {"status": "failed", "task": current}
	task = frappe.get_doc(
		{
			"doctype": "CRM Student Task",
			"student": student,
			"current_slot": "CURRENT",
			"source_context_revision": source_revision,
			"disposition": "MONITOR",
			"objective": "Generation failed; reconcile this Student context.",
			"policy_version": "student-next-task-v2",
			"context_version": "generation-failure",
			"state": "PENDING",
			"generation_status": "failed",
			"generation_failed_at": frappe.utils.now_datetime(),
			"generation_failure_reason": str(reason)[:500],
			"generation_idempotency_key": f"failure:{student}:{source_revision}",
			"producer_identity": "crm-agents:v2",
			"payload_digest": "0" * 64,
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	return {"status": "failed", "task": task.name}


def _call(fn, **kwargs):
	try:
		return fn(**kwargs)
	except StudentDecisionError as exc:
		exc_type = frappe.PermissionError if exc.code in {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE", "CONTRACT_UNAVAILABLE", "OUTBOX_DISABLED"} else frappe.ValidationError
		frappe.throw(str(exc), exc_type)


def _decide_by_name(name: str, **kwargs):
	"""Dispatch to the V2 task-native command when `name` names a CRM Student
	Task; CRM Recommendation only ever holds pre-cutover historical rows."""
	fn = _decide_student_task if frappe.db.exists("CRM Student Task", name) else _decide_recommendation
	result = _call(fn, name=name, **kwargs)
	result.setdefault("name", result.get("recommendation") or result.get("task"))
	return result


@frappe.whitelist(methods=["POST"])
def transition_recommendation(name: str, expected_revision: str, status: str, decision_reason: str | None = None, **kwargs):
	"""Compatibility adapter for the pre-Phase-6 Desk/demo call shape.

	New clients must send an idempotency key and the decision revision. This
	adapter only translates legacy callers; it does not restore direct document
	writes or bypass the Phase 6 command service.
	"""
	if kwargs.get("idempotency_key"):
		return _decide_by_name(
			name,
			expected_revision=expected_revision,
			status=status,
			decision_reason=decision_reason,
			due_at=kwargs.get("due_at"),
			assignee_staff=kwargs.get("assignee_staff"),
			revisit_at=kwargs.get("revisit_at"),
			defer_kind=kwargs.get("defer_kind"),
			idempotency_key=kwargs["idempotency_key"],
			correlation_id=kwargs.get("correlation_id"),
		)
	doc = frappe.get_doc("CRM Recommendation", name)
	legacy_modified = str(doc.modified) == str(expected_revision)
	result = _call(
		_decide_recommendation,
		name=name,
		expected_revision=(doc.get("decision_revision") or 0) if legacy_modified else expected_revision,
		status=status,
		decision_reason=decision_reason,
		due_at=kwargs.get("due_at") or doc.get("recommended_timing") or now_datetime(),
		revisit_at=kwargs.get("revisit_at"),
		defer_kind=kwargs.get("defer_kind"),
		idempotency_key=kwargs.get("idempotency_key") or f"legacy-decision-{name}-{expected_revision}-{status}",
		correlation_id=kwargs.get("correlation_id") or f"legacy-decision-{name}",
		expected_modified=str(expected_revision) if legacy_modified else None,
	)
	result.setdefault("name", result.get("recommendation"))
	return result


@frappe.whitelist(methods=["POST"])
def decide_recommendation(name: str, **kwargs):
	return _decide_by_name(name, **kwargs)


@frappe.whitelist(methods=["POST"])
def record_sales_action_outcome(name: str, expected_revision: str, business_outcome: str, outcome_notes: str | None = None):
	"""Compatibility adapter for the retired one-call completion endpoint."""
	action = frappe.get_doc("CRM Sales Action", name)
	result = _call(
		_transition_sales_action,
		name=name,
		expected_revision=action.get("action_revision") or 1,
		status="completed",
		outcome_code=business_outcome,
		evidence=outcome_notes,
		idempotency_key=f"legacy-outcome-{name}-{expected_revision}",
		correlation_id=f"legacy-outcome-{name}",
		expected_modified=str(expected_revision) if str(action.modified) == str(expected_revision) else None,
	)
	result.setdefault("name", result.get("sales_action"))
	return result


@frappe.whitelist(methods=["POST"])
def transition_sales_action(**kwargs):
	kwargs.pop("_internal_service", None)
	return _call(_transition_sales_action, **kwargs)


@frappe.whitelist(methods=["POST"])
def reassign_sales_action(**kwargs):
	kwargs.pop("_internal_service", None)
	return _call(_reassign_sales_action, **kwargs)


@frappe.whitelist()
def get_sales_action(name: str) -> dict:
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	doc = frappe.get_doc("CRM Sales Action", name)
	if not doc.has_permission("read"):
		frappe.throw("You do not have permission to view this Sales Action.", frappe.PermissionError)
	return {"name": doc.name, "student": doc.student, "action_type": doc.action_type, "status": doc.execution_status, "revision": doc.get("action_revision") or 1}
