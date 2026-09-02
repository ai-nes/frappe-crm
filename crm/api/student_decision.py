"""Thin HTTP adapters for Phase 6 decision commands."""
from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.doctype.crm_action.crm_action import CRMAction
from crm.fcrm.student_decision import (
	StudentDecisionError,
)
from crm.fcrm.student_decision import (
	create_manual_action as _create_manual_action,
)
from crm.fcrm.student_decision import (
	decide_recommendation as _decide_recommendation,
)
from crm.fcrm.student_decision import (
	decide_student_task as _decide_student_task,
)
from crm.fcrm.student_decision import (
	reassign_action as _reassign_action,
)
from crm.fcrm.student_decision import (
	transition_action as _transition_action,
)


def _require_v2_service():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			_("This command is restricted to the crm-agents service identity."), frappe.PermissionError
		)


def _throw_revision_conflict(message: str, current_revision: int):
	"""Raise a backward-compatible 409 with the winning revision in its body."""
	frappe.local.response["current_revision"] = int(current_revision)
	error = frappe.ValidationError(message)
	error.http_status_code = 409
	frappe.throw(message, error)


def _task_result(task, *, idempotent=False):
	return {
		"name": task.name,
		"action": task.name,
		"student": task.student,
		"state": task.state,
		"disposition": task.disposition,
		"action_type": task.action_type,
		"generation_status": task.get("generation_status") or "succeeded",
		"generation_failed_at": str(task.get("generation_failed_at")) if task.get("generation_failed_at") else None,
		"source_context_revision": task.source_context_revision,
		"task_revision": str(task.modified),
		"action_revision": int(task.get("action_revision") or 0),
		"owner": task.get("action_owner"),
		"recommendation": task.get("recommendation"),
		"idempotent": idempotent,
	}


@frappe.whitelist()
def _upsert_crm_action(
	student: str,
	expected_context_revision: int,
	generation_idempotency_key: str,
	producer_identity: str,
	payload_digest: str,
	rollout_epoch: int,
	candidate: dict | str,
	origin: str = "ai",
	writer_epoch: int | None = None,
	source_stage_key: str | None = None,
	run_id: str | None = None,
	stage_kind: str | None = None,
	stage_generation: int | None = None,
	lease_token: str | None = None,
	expected_source_digest: str | None = None,
) -> dict:
	"""Only mutation endpoint for v2 generation; compare-and-swap + idempotency."""
	_require_v2_service()
	if origin != "ai":
		frappe.throw(_("AI generation must use origin=ai."), frappe.ValidationError)
	if isinstance(candidate, str):
		candidate = frappe.parse_json(candidate)
	if not isinstance(candidate, dict):
		frappe.throw(_("Candidate must be an object."), frappe.ValidationError)
	canonical = json.dumps(candidate, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
	if hashlib.sha256(canonical.encode()).hexdigest() != payload_digest:
		frappe.throw(_("Candidate payload digest does not match."), frappe.ValidationError)
	if int(expected_context_revision) < 0 or int(rollout_epoch) < 0:
		frappe.throw(_("Invalid revision."), frappe.ValidationError)
	active_writer_epoch = frappe.conf.get("crm_intelligence_writer_epoch")
	if active_writer_epoch is not None:
		if writer_epoch is None or int(writer_epoch) != int(active_writer_epoch):
			frappe.throw(_("writer_retired"), frappe.PermissionError)
		if not all((run_id, stage_kind, lease_token, expected_source_digest)) or stage_generation is None:
			frappe.throw(_("Active Intelligence Run NBA writer requires a fenced run stage."), frappe.PermissionError)
		if stage_kind != "next_best_action":
			frappe.throw(_("Invalid Intelligence Run stage kind for Action write."), frappe.ValidationError)
		from crm.fcrm.intelligence_runs import authorize_next_best_action_write
		stage_authority = authorize_next_best_action_write(
			run_id=str(run_id), stage_generation=int(stage_generation), lease_token=str(lease_token),
			expected_source_revision=str(expected_context_revision), expected_source_digest=str(expected_source_digest),
		)
		if stage_authority["student"] != student or stage_authority["stage_key"] != source_stage_key:
			frappe.throw(_("Intelligence Run stage does not authorize this Student Action write."), frappe.PermissionError)
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
	existing_filters = {"student": student, "generation_idempotency_key": generation_idempotency_key}
	if source_stage_key:
		existing_filters = {"student": student, "source_stage_key": source_stage_key}
	existing = frappe.db.get_value(
		"CRM Action", existing_filters,
		["name", "payload_digest"],
		as_dict=True,
	)
	if existing:
		if existing.payload_digest != payload_digest:
			frappe.throw(_("Generation idempotency key was reused with a different payload."), frappe.ValidationError)
		return _task_result(frappe.get_doc("CRM Action", existing.name), idempotent=True)
	current_revision = int(row[0].student_context_revision or 0)
	if current_revision != int(expected_context_revision):
		_throw_revision_conflict(
			_("Student context changed; retry from the newer projection."), current_revision
		)
	current = frappe.db.sql(
		"SELECT name, state FROM `tabCRM Action` WHERE student = %s AND current_slot = 'CURRENT' FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if current:
		if str(current[0].state) in {"accepted", "in-progress", "requires-review", "completed"}:
			task = frappe.get_doc("CRM Action", current[0].name)
			task.requires_review = 1
			task.review_revision = current_revision
			task.state = "requires-review"
			frappe.flags.crm_action_command = True
			try:
				task.save(ignore_permissions=True)
			finally:
				frappe.flags.crm_action_command = False
			return _task_result(task)
		frappe.db.set_value(
			"CRM Action",
			current[0].name,
			{"current_slot": None, "state": "superseded"},
			update_modified=False,
		)
	from crm.services.sales_action_policy import V2_ACTION_TYPES

	if action_type and action_type not in V2_ACTION_TYPES:
		frappe.throw(_("Unsupported v2 action type."), frappe.ValidationError)
	task = frappe.get_doc(
		{
			"doctype": "CRM Action",
			"student": student,
			"contact": frappe.db.get_value("CRM Contact", {"student": student}, "name"),
			"origin": "ai",
			"current_slot": "CURRENT",
			"source_context_revision": current_revision,
			"disposition": disposition,
			"action_type": action_type,
			"objective": str(candidate.get("objective") or "")[:500],
			"policy_context_version": candidate.get("policy_version"),
			"state": "pending",
			"requires_review": 0,
			"action_revision": 1,
			"execution_package_version": 1 if action_type else 0,
			"generation_idempotency_key": generation_idempotency_key,
			"producer_identity": producer_identity,
			"writer_epoch": writer_epoch,
			"source_stage_key": source_stage_key,
			"payload_digest": payload_digest,
			"evidence_references": json.dumps(candidate.get("evidence_refs", []), separators=(",", ":")),
			"package_seed": json.dumps(candidate.get("package_seed") or {}, separators=(",", ":")),
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	return _task_result(task)


def _default_action_owner(student: str) -> str | None:
	"""The CRM Staff who cares for this student, for a new AI Action's owner.

	Set only at insert time so a later human reassignment is never overwritten
	by an idempotent regeneration. Absent ``owner_staff`` leaves the Action
	unassigned rather than guessing.
	"""
	return frappe.db.get_value("CRM Student", student, "owner_staff") or None


def _plan_rank_defaults(rank: int) -> dict:
	"""Slot / state / priority for a bundle row at ``rank`` (1-based).

	Rank 1 is the live recommendation; ranks 2-3 are backlog alternatives held
	``deferred`` so they never enter the active worklist or an SLA aggregate.
	"""
	if rank == 1:
		return {"current_slot": "CURRENT", "state": "pending", "priority": "high"}
	return {
		"current_slot": None,
		"state": "deferred",
		"priority": "medium" if rank == 2 else "low",
		"worklist_priority_rank": rank,
	}


def _merge_rationale(package_seed: dict | None, rationale: dict | None) -> dict:
	"""Fold the advisory NBA narration into the package blob.

	The rationale (why now / approach / expected outcome) arrives outside the
	hashed candidate — it never took part in ``payload_digest`` — and is stored
	here so the workbench can render the "tại sao bây giờ" block without a
	second round trip. Absent rationale leaves the package untouched.
	"""
	seed = dict(package_seed or {})
	if not rationale:
		return seed
	block: dict = {}
	for key in ("why_now", "approach", "expected_outcome"):
		value = rationale.get(key)
		if isinstance(value, str) and value.strip():
			block[key] = value.strip()[:600]
	refs = rationale.get("evidence_ref_ids")
	if isinstance(refs, list):
		block["evidence_ref_ids"] = [str(r)[:140] for r in refs if r][:8]
	if block:
		# One reserved, nested key — never flat fields — so a strict package
		# validator (`PackageSeedV2`, `validate_execution_package`) treats the
		# advisory narration as a single known slot, not "unsupported fields".
		seed["rationale"] = block
	return seed


def _insert_bundle_action(*, student, contact, candidate, current_revision, rank, base_idempotency_key, base_stage_key, producer_identity, payload_digest, writer_epoch, rationale=None):
	from crm.services.sales_action_policy import V2_ACTION_TYPES

	action_type = candidate.get("action_type")
	disposition = candidate.get("disposition")
	if disposition not in {"ACT", "MONITOR", "NURTURE"} or (disposition == "ACT") != bool(action_type):
		frappe.throw(_("Invalid v2 disposition/action combination."), frappe.ValidationError)
	if action_type and action_type not in V2_ACTION_TYPES:
		frappe.throw(_("Unsupported v2 action type."), frappe.ValidationError)
	doc = {
		"doctype": "CRM Action",
		"student": student,
		"contact": contact,
		"origin": "ai",
		"plan_rank": rank,
		"source_context_revision": current_revision,
		"disposition": disposition,
		"action_type": action_type,
		"action_owner": _default_action_owner(student),
		"objective": str(candidate.get("objective") or "")[:500],
		"policy_context_version": candidate.get("policy_version"),
		"requires_review": 0,
		"action_revision": 1,
		"execution_package_version": 1 if action_type else 0,
		"generation_idempotency_key": f"{base_idempotency_key}:r{rank}",
		"producer_identity": producer_identity,
		"writer_epoch": writer_epoch,
		"source_stage_key": f"{base_stage_key}:r{rank}",
		"payload_digest": payload_digest,
		"evidence_references": json.dumps(candidate.get("evidence_refs", []), separators=(",", ":")),
		"package_seed": json.dumps(
			_merge_rationale(candidate.get("package_seed"), rationale), separators=(",", ":")
		),
		"created_at": frappe.utils.now_datetime(),
	}
	doc.update(_plan_rank_defaults(rank))
	return frappe.get_doc(doc).insert(ignore_permissions=True)


def _upsert_crm_action_bundle(
	*,
	student: str,
	expected_context_revision: int,
	base_idempotency_key: str,
	base_stage_key: str,
	producer_identity: str,
	payload_digest: str,
	rollout_epoch: int,
	writer_epoch: int | None,
	candidates: list[dict],
	rationales: list[dict] | None = None,
) -> dict:
	"""Insert 1-3 priority-ranked CRM Action rows for one NBA analysis.

	One student lock, one revision CAS, one CURRENT-slot vacate, then a row per
	rank with a per-rank idempotency key. The whole bundle lands in the caller's
	request transaction.
	"""
	_require_v2_service()
	if not isinstance(candidates, list) or not 1 <= len(candidates) <= 3:
		frappe.throw(_("A Next Best Action bundle needs 1-3 candidates."), frappe.ValidationError)
	canonical = json.dumps(candidates, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
	if hashlib.sha256(canonical.encode()).hexdigest() != payload_digest:
		frappe.throw(_("Bundle payload digest does not match."), frappe.ValidationError)
	if int(expected_context_revision) < 0 or int(rollout_epoch) < 0:
		frappe.throw(_("Invalid revision."), frappe.ValidationError)
	act_types = [c.get("action_type") for c in candidates if c.get("disposition") == "ACT"]
	if len(set(act_types)) != len(act_types):
		frappe.throw(_("Bundle candidates must have distinct action types."), frappe.ValidationError)
	for candidate in candidates:
		if int(candidate.get("context_revision", -1)) != int(expected_context_revision):
			frappe.throw(_("Candidate revision does not match expected context revision."), frappe.ValidationError)

	active_writer_epoch = frappe.conf.get("crm_intelligence_writer_epoch")
	if active_writer_epoch is not None and (writer_epoch is None or int(writer_epoch) != int(active_writer_epoch)):
		frappe.throw(_("writer_retired"), frappe.PermissionError)
	if frappe.conf.get("crm_agents_v2_rollout_epoch") is not None and int(
		frappe.conf.get("crm_agents_v2_rollout_epoch", 0)
	) != int(rollout_epoch):
		frappe.throw(_("Stale rollout epoch."), frappe.ValidationError)

	row = frappe.db.sql(
		"SELECT name, student_context_revision FROM `tabCRM Student` WHERE name = %s FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Student not found."), frappe.DoesNotExistError)

	existing = frappe.db.get_value(
		"CRM Action",
		{"student": student, "source_stage_key": f"{base_stage_key}:r1"},
		["name", "payload_digest"],
		as_dict=True,
	)
	if existing:
		if existing.payload_digest != payload_digest:
			frappe.throw(_("Bundle idempotency key was reused with a different payload."), frappe.ValidationError)
		rows = frappe.get_all(
			"CRM Action",
			filters={"student": student, "source_stage_key": ["like", f"{base_stage_key}:r%"]},
			fields=["name", "plan_rank"],
			order_by="plan_rank asc",
		)
		return {
			"status": "completed",
			"idempotent": True,
			"actions": [{"name": r.name, "plan_rank": r.plan_rank} for r in rows],
		}

	current_revision = int(row[0].student_context_revision or 0)
	if current_revision != int(expected_context_revision):
		_throw_revision_conflict(
			_("Student context changed; retry from the newer projection."), current_revision
		)

	current = frappe.db.sql(
		"SELECT name, state FROM `tabCRM Action` WHERE student = %s AND current_slot = 'CURRENT' FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if current:
		stale = frappe.get_doc("CRM Action", current[0].name)
		previous_flag = getattr(frappe.flags, "crm_action_command", False)
		frappe.flags.crm_action_command = True
		try:
			if str(stale.state) in {"accepted", "in-progress", "requires-review"}:
				stale.requires_review = 1
				stale.review_revision = current_revision
				stale.state = "requires-review"
				stale.save(ignore_permissions=True)
				return {"status": "requires_review", "action": stale.name}
			if str(stale.state) not in CRMAction.TERMINAL:
				stale.state = "superseded"
			stale.current_slot = None
			stale.save(ignore_permissions=True)
		finally:
			frappe.flags.crm_action_command = previous_flag

	contact = frappe.db.get_value("CRM Contact", {"student": student}, "name")
	rationale_by_type = {
		r.get("action_type"): r for r in (rationales or []) if isinstance(r, dict) and r.get("action_type")
	}
	inserted = []
	for rank, candidate in enumerate(candidates, start=1):
		task = _insert_bundle_action(
			student=student,
			contact=contact,
			candidate=candidate,
			current_revision=current_revision,
			rank=rank,
			base_idempotency_key=base_idempotency_key,
			base_stage_key=base_stage_key,
			producer_identity=producer_identity,
			payload_digest=payload_digest,
			writer_epoch=writer_epoch,
			rationale=rationale_by_type.get(candidate.get("action_type")),
		)
		inserted.append({"name": task.name, "plan_rank": rank})
	return {"status": "completed", "idempotent": False, "actions": inserted}


@frappe.whitelist()
def _record_crm_action_generation_failure(
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
	current = frappe.db.get_value("CRM Action", {"student": student, "current_slot": "CURRENT"}, "name")
	if current:
		frappe.db.set_value(
			"CRM Action",
			current,
			{
				"state": "requires-review",
				"terminal_reason": str(reason)[:500],
			},
			update_modified=False,
		)
		return {"status": "failed", "action": current}
	task = frappe.get_doc(
		{
			"doctype": "CRM Action",
			"student": student,
			"current_slot": "CURRENT",
			"source_context_revision": source_revision,
			"disposition": "MONITOR",
			"objective": "Generation failed; reconcile this Student context.",
			"policy_context_version": "student-next-task-v2:generation-failure",
			"state": "pending",
			"generation_idempotency_key": f"failure:{student}:{source_revision}",
			"producer_identity": "crm-agents:v2",
			"payload_digest": "0" * 64,
			"created_at": frappe.utils.now_datetime(),
		}
	).insert(ignore_permissions=True)
	return {"status": "failed", "action": task.name}


@frappe.whitelist()
def upsert_crm_action(**kwargs):
	"""Canonical idempotent CRM Action generation command."""
	return _upsert_crm_action(**kwargs)


@frappe.whitelist()
def record_crm_action_generation_failure(**kwargs):
	"""Canonical name for bounded CRM Action failure recording."""
	return _record_crm_action_generation_failure(**kwargs)


def _call(fn, **kwargs):
	try:
		return fn(**kwargs)
	except StudentDecisionError as exc:
		exc_type = frappe.PermissionError if exc.code in {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE", "CONTRACT_UNAVAILABLE", "OUTBOX_DISABLED"} else frappe.ValidationError
		frappe.throw(str(exc), exc_type)


def _decide_by_name(name: str, **kwargs):
	"""Dispatch to the V2 task-native command when `name` names a CRM Student
	Task; CRM Recommendation only ever holds pre-cutover historical rows."""
	fn = _decide_student_task if frappe.db.exists("CRM Action", name) else _decide_recommendation
	result = _call(fn, name=name, **kwargs)
	result.setdefault("name", result.get("recommendation") or result.get("action"))
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
def create_action(**kwargs):
	"""Manual Sale -> Action command; AI acceptance uses the same aggregate."""
	kwargs.pop("_internal_service", None)
	try:
		return _create_manual_action(**kwargs)
	except StudentDecisionError as exc:
		exc_type = frappe.PermissionError if exc.code in {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE"} else frappe.ValidationError
		frappe.throw(str(exc), exc_type)


@frappe.whitelist(methods=["POST"])
def transition_action(**kwargs):
	"""Canonical Action lifecycle endpoint."""
	kwargs.pop("_internal_service", None)
	return _call(_transition_action, **kwargs)


@frappe.whitelist(methods=["POST"])
def reassign_action(**kwargs):
	kwargs.pop("_internal_service", None)
	return _call(_reassign_action, **kwargs)


@frappe.whitelist()
def get_action(name: str) -> dict:
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	doc = frappe.get_doc("CRM Action", name)
	if not doc.has_permission("read"):
		frappe.throw("You do not have permission to view this Action.", frappe.PermissionError)
	return {"name": doc.name, "student": doc.student, "contact": doc.get("contact"), "action_type": doc.action_type, "status": doc.get("execution_status") or doc.state, "revision": doc.get("action_revision") or 1}
