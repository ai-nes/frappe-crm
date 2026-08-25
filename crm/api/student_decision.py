"""Permissioned, compare-and-set transitions for CRM Recommendations."""

import hashlib
import json

import frappe
from frappe import _

_TASK_TRANSITIONS = {
	"PENDING": {"ACCEPTED", "CANCELLED", "SUPERSEDED"},
	"ACCEPTED": {"IN_PROGRESS", "COMPLETED", "CANCELLED", "REQUIRES_REVIEW"},
	"IN_PROGRESS": {"COMPLETED", "CANCELLED", "REQUIRES_REVIEW"},
	"REQUIRES_REVIEW": {"ACCEPTED", "IN_PROGRESS", "COMPLETED", "CANCELLED"},
}


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
		frappe.throw(
			_("Candidate revision does not match expected context revision."), frappe.ValidationError
		)
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
			frappe.throw(
				_("Generation idempotency key was reused with a different payload."), frappe.ValidationError
			)
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
			# Frappe JSON fields are persisted as serialized JSON at this API
			# boundary; keeping the wire contract as arrays/objects avoids
			# leaking storage-specific encoding to crm-agents.
			"evidence_references": json.dumps(candidate.get("evidence_refs", []), separators=(",", ":")),
			"package_seed": json.dumps(candidate.get("package_seed") or {}, separators=(",", ":")),
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	if disposition == "ACT":
		recommendation = frappe.get_doc(
			{
				"doctype": "CRM Recommendation",
				"student": student,
				"rule_key": "student_next_task_v2",
				"source_intent_id": f"v2:{generation_idempotency_key}",
				"condition_version": 2,
				"context_hash": payload_digest,
				"policy_version": candidate.get("policy_version"),
				"priority": "medium",
				"status": "new",
				"recommended_action": action_type,
				"reason": task.objective,
				"evidence": {"references": candidate.get("evidence_refs", [])},
			}
		).insert(ignore_permissions=True)
		task.db_set("recommendation", recommendation.name, update_modified=False)
		task.reload()
	return _task_result(task)


@frappe.whitelist()
def record_student_task_generation_failure(
	student: str, source_revision: int, reason: str, rollout_epoch: int = 0
) -> dict:
	"""Persist an explicit bounded failure for the five-minute convergence SLO."""
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
		task = frappe.get_doc("CRM Student Task", current)
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
		return {"status": "failed", "task": task.name}
	task = frappe.get_doc(
		{
			"doctype": "CRM Student Task",
			"student": student,
			"current_slot": "CURRENT",
			"source_context_revision": source_revision,
			"disposition": "MONITOR",
			"action_type": None,
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


def _transition_student_task(name, expected_task_revision, target_state, *, outcome=None):
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	task = frappe.get_doc("CRM Student Task", name)
	if not task.has_permission("write"):
		frappe.throw(_("You do not have permission to change this task."), frappe.PermissionError)
	if str(task.modified) != str(expected_task_revision):
		frappe.throw(_("Task changed; refresh before issuing a command."), frappe.ValidationError)
	if target_state not in _TASK_TRANSITIONS.get(task.state, set()):
		frappe.throw(_("Illegal Student Task transition."), frappe.ValidationError)
	if task.disposition != "ACT":
		frappe.throw(
			_("MONITOR and NURTURE decisions are immutable and not executable."), frappe.ValidationError
		)
	if task.action_type:
		if target_state == "ACCEPTED":
			from crm.services.sales_action_dispatch import persist_initial_package

			frappe.flags.student_task_command = True
			try:
				task.package_seed = persist_initial_package(task)
				task.execution_package_version = max(int(task.execution_package_version or 0), 1)
			finally:
				frappe.flags.student_task_command = False
		from crm.services.sales_action_policy import validate_action_command

		roles = set(frappe.get_roles(frappe.session.user))
		validate_action_command(
			task.action_type,
			student=task.student,
			inputs={
				"objective": task.objective,
				"package": task.package_seed or {},
				"authority": True,
				"channel": "email",
				"timing": True,
			},
			actor_roles=roles,
		)
	task.state = target_state
	if target_state == "REQUIRES_REVIEW":
		task.requires_review = 1
		task.review_revision = task.source_context_revision
	if outcome:
		task.outcome = outcome
	frappe.flags.student_task_command = True
	try:
		task.save()
	finally:
		frappe.flags.student_task_command = False
	if target_state in {"COMPLETED", "CANCELLED"}:
		frappe.db.set_value("CRM Student Task", task.name, "current_slot", None, update_modified=False)
	if target_state == "COMPLETED" and outcome:
		from crm.services.student_context import mark_student_context_changed

		mark_student_context_changed(task.student, "student_task_outcome")
	if (
		target_state == "ACCEPTED"
		and task.disposition == "ACT"
		and task.recommendation
		and not task.sales_action
	):
		from frappe.utils import now_datetime

		from crm.fcrm.doctype.crm_recommendation.crm_recommendation import _create_sales_action

		recommendation = frappe.get_doc("CRM Recommendation", task.recommendation)
		frappe.flags.student_task_command = True
		try:
			action_name = _create_sales_action(recommendation)
		finally:
			frappe.flags.student_task_command = False
		frappe.db.set_value(
			"CRM Sales Action",
			action_name,
			{
				"student_task": task.name,
				"action_revision": task.action_revision or 1,
				"package_revision": task.execution_package_version or 1,
			},
			update_modified=False,
		)
		frappe.db.set_value("CRM Student Task", task.name, "sales_action", action_name, update_modified=False)
		task.reload()
	return _task_result(task)


@frappe.whitelist()
def edit_email_package(name: str, expected_package_revision: int, package: dict | str, reason: str) -> dict:
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if isinstance(package, str):
		package = frappe.parse_json(package)
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles.intersection({"Sale", "Lead Sales", "System Manager"}):
		frappe.throw(_("Only Sales may edit an Email Package."), frappe.PermissionError)
	from crm.services.sales_action_dispatch import edit_email_package as _edit

	return _edit(name, int(expected_package_revision), package, reason)


@frappe.whitelist()
def accept_student_task(name: str, expected_task_revision: str) -> dict:
	return _transition_student_task(name, expected_task_revision, "ACCEPTED")


@frappe.whitelist()
def start_student_task(name: str, expected_task_revision: str) -> dict:
	return _transition_student_task(name, expected_task_revision, "IN_PROGRESS")


@frappe.whitelist()
def complete_student_task(name: str, expected_task_revision: str, outcome: str | None = None) -> dict:
	return _transition_student_task(name, expected_task_revision, "COMPLETED", outcome=outcome)


@frappe.whitelist()
def cancel_student_task(name: str, expected_task_revision: str, outcome: str | None = None) -> dict:
	return _transition_student_task(name, expected_task_revision, "CANCELLED", outcome=outcome)


@frappe.whitelist()
def transition_recommendation(
	name: str, expected_revision: str, status: str, decision_reason: str | None = None
) -> dict:
	"""Apply a legal decision only if the client still holds the CRM revision.

	No caller-selected user, campus, or role scope is accepted. Frappe's own
	session plus document permission hooks determine visibility and authority.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	doc = frappe.get_doc("CRM Recommendation", name)
	if not doc.has_permission("write"):
		frappe.throw(_("You do not have permission to decide this recommendation."), frappe.PermissionError)
	if str(doc.modified) != expected_revision:
		frappe.throw(_("Recommendation changed; refresh before deciding."), frappe.ValidationError)
	doc.status = status
	doc.decision_reason = decision_reason
	doc.save()
	action = frappe.db.get_value("CRM Sales Action", {"recommendation": doc.name}, "name")
	return {
		"name": doc.name,
		"status": doc.status,
		"source_revision": str(doc.modified),
		"sales_action": action,
	}


@frappe.whitelist()
def record_sales_action_outcome(
	name: str, expected_revision: str, business_outcome: str, outcome_notes: str | None = None
) -> dict:
	"""CAS-protected outcome entry for a Sales Action the caller may write."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	doc = frappe.get_doc("CRM Sales Action", name)
	if not doc.has_permission("write"):
		frappe.throw(_("You do not have permission to record this outcome."), frappe.PermissionError)
	if str(doc.modified) != expected_revision:
		frappe.throw(_("Sales Action changed; refresh before recording an outcome."), frappe.ValidationError)
	if business_outcome not in {
		"NO_RESPONSE",
		"INTEREST_INCREASED",
		"NEEDS_MORE_INFORMATION",
		"CALL_BACK_LATER",
		"APPLICATION_STARTED",
		"APPLICATION_COMPLETED",
		"NOT_INTERESTED",
	}:
		frappe.throw(_("Invalid business outcome."), frappe.ValidationError)
	doc.business_outcome = business_outcome
	doc.outcome_notes = outcome_notes
	doc.execution_status = "completed"
	frappe.flags.student_task_command = True
	try:
		doc.save()
	finally:
		frappe.flags.student_task_command = False
	return {"name": doc.name, "source_revision": str(doc.modified)}


@frappe.whitelist()
def get_sales_action(name: str) -> dict:
	"""Return the small, permission-checked projection needed by the Desk outcome control."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	doc = frappe.get_doc("CRM Sales Action", name)
	if not doc.has_permission("read"):
		frappe.throw(_("You do not have permission to view this Sales Action."), frappe.PermissionError)
	return {"name": doc.name, "action_type": doc.action_type, "source_revision": str(doc.modified)}
