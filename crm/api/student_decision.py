"""Decision command adapters and the canonical CRM Action storage primitive."""
from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _

from crm.fcrm.action_type_catalog import action_category
from crm.fcrm.doctype.crm_action_item.crm_action_item import CRMActionItem
from crm.fcrm.student_decision import (
	StudentDecisionError,
)
from crm.fcrm.student_decision import (
	claim_current_action as _claim_current_action,
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


def _require_action_writer():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	if frappe.session.user == "Administrator":
		return
	configured = frappe.conf.get("crm_agents_service_user")
	if not configured or frappe.session.user != configured:
		frappe.throw(
			_("This command is restricted to the crm-agents service identity."), frappe.PermissionError
		)


def _require_legacy_generation_epoch():
	"""Block legacy AI generation writes while the NBA Evaluation epoch is active.

	The Evaluation runtime and the legacy generation path must never both write:
	when the epoch is on, generation produces its own recommendation rows and no
	``CRM Action Item``. A missing or malformed flag keeps the legacy path live.
	"""
	from crm.fcrm.nba import nba_evaluation_epoch_active

	if nba_evaluation_epoch_active():
		frappe.throw(
			_("The NBA Evaluation runtime owns recommendation generation; the legacy Action writer is disabled."),
			frappe.ValidationError,
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
		"action_code": task.get("action"),
		"generation_status": task.get("generation_status") or "succeeded",
		"generation_failed_at": str(task.get("generation_failed_at")) if task.get("generation_failed_at") else None,
		"source_context_revision": task.source_context_revision,
		"task_revision": str(task.modified),
		"action_revision": int(task.get("action_revision") or 0),
		"owner": task.get("action_owner"),
		"recommendation": task.get("recommendation"),
		"idempotent": idempotent,
	}


def write_canonical_action(
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
	"""Canonical CRM Action storage writer; compare-and-swap plus idempotency."""
	_require_action_writer()
	_require_legacy_generation_epoch()
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
		# The fenced child-stage NBA writer was retired when NBA Evaluation became
		# an independent runtime.  Never resurrect that dependency through this
		# legacy Action command.
		frappe.throw(_("writer_retired"), frappe.PermissionError)
	if frappe.conf.get("crm_agents_v2_rollout_epoch") is not None and int(
		frappe.conf.get("crm_agents_v2_rollout_epoch", 0)
	) != int(rollout_epoch):
		frappe.throw(_("Stale rollout epoch."), frappe.ValidationError)
	from crm.fcrm.action_type_catalog import canonicalize_action_type

	action_type = canonicalize_action_type(candidate.get("action_type"))
	disposition = candidate.get("disposition")
	from crm.fcrm.action_type_registry import is_available_action_type
	from crm.services.sales_action_policy import require_parent_contact_authority

	if int(candidate.get("context_revision", -1)) != int(expected_context_revision):
		frappe.throw(_("Candidate revision does not match expected context revision."), frappe.ValidationError)
	if disposition not in {"ACT", "MONITOR", "NURTURE"} or (disposition == "ACT") != bool(action_type):
		frappe.throw(_("Invalid v2 disposition/action combination."), frappe.ValidationError)
	if action_type and not is_available_action_type(action_type):
		frappe.throw(_("Unsupported v2 action type."), frappe.ValidationError)
	require_parent_contact_authority(action_type, student)
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
		"CRM Action Item", existing_filters,
		["name", "payload_digest"],
		as_dict=True,
	)
	if existing:
		if existing.payload_digest != payload_digest:
			frappe.throw(_("Generation idempotency key was reused with a different payload."), frappe.ValidationError)
		return _task_result(frappe.get_doc("CRM Action Item", existing.name), idempotent=True)
	current_revision = int(row[0].student_context_revision or 0)
	if current_revision != int(expected_context_revision):
		_throw_revision_conflict(
			_("Student context changed; retry from the newer projection."), current_revision
		)
	current = frappe.db.sql(
		"SELECT name, state FROM `tabCRM Action Item` WHERE student = %s AND current_slot = 'CURRENT' FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if current:
		stale = frappe.get_doc("CRM Action Item", current[0].name)
		previous_flag = getattr(frappe.flags, "crm_action_command", False)
		frappe.flags.crm_action_command = True
		try:
			if str(stale.state) in {"accepted", "in-progress", "requires-review"}:
				# Live work in flight: a newer context forces a human review, it does
				# not silently overwrite the executor's Action.
				stale.requires_review = 1
				stale.review_revision = current_revision
				stale.state = "requires-review"
				stale.save(ignore_permissions=True)
				return _task_result(stale)
			# A completed (or otherwise closed) Action is never reopened. Vacate the
			# slot so this new recommendation opens a fresh Action; supersede it
			# only when that is a legal transition from its current state.
			if str(stale.state) not in CRMActionItem.TERMINAL:
				stale.state = "superseded"
			stale.current_slot = None
			stale.save(ignore_permissions=True)
			from crm.fcrm.nba import sync_nba_recommendation_for_action
			sync_nba_recommendation_for_action(stale)
		finally:
			frappe.flags.crm_action_command = previous_flag
	from crm.fcrm.nba import ensure_nba_recommendation
	_validate_package_seed(candidate.get("package_seed"), action_type)
	owner_staff = _default_action_owner(student)
	nba_recommendation = ensure_nba_recommendation(
		student=student,
		action_type=action_type,
		objective=str(candidate.get("objective") or "")[:500],
		evidence=candidate.get("evidence_refs", []),
		priority=str(candidate.get("priority") or "medium"),
		due_at=candidate.get("due_at"),
		expires_at=candidate.get("expires_at"),
		owner=owner_staff,
		trigger=candidate.get("trigger") or source_stage_key,
		timing_policy=candidate.get("timing_policy"),
		confidence=candidate.get("confidence"),
		expected_impact=candidate.get("expected_impact"),
		model=candidate.get("model"),
		model_version=candidate.get("model_version"),
	)
	task = frappe.get_doc(
		{
			"doctype": "CRM Action Item",
			"student": student,
			"contact": frappe.db.get_value("CRM Contact", {"student": student}, "name"),
			"recommendation": nba_recommendation.name if nba_recommendation else None,
			"action": nba_recommendation.get("action") if nba_recommendation else action_type,
			"origin": "ai",
			"current_slot": "CURRENT",
			"source_context_revision": current_revision,
			"disposition": disposition,
			"action_type": action_category(action_type),
			"action_owner": _default_action_owner(student),
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


# Top-level package_seed keys each action type legitimately carries. Mirrors
# crm-agents `app.services.decision.action_packages.PACKAGE_FIELD_SETS`; kept in
# lockstep by a paired test on each side. Shape only — the writer never edits
# package content, this just logs drift.
_PACKAGE_ENVELOPE_KEYS = frozenset({"package_version", "objective", "rationale"})
_PACKAGE_FIELD_SETS: dict[str, frozenset[str]] = {
	"CALL": frozenset({"opening", "talking_points", "questions", "objections", "desired_outcome", "next_step"}),
	"EMAIL": frozenset(
		{"template_version", "recipient_ref", "subject", "body", "talking_points", "questions", "cta", "next_step"}
	),
	"MESSAGE": frozenset({"channel", "opening", "key_points", "cta", "next_step"}),
	"COUNSELING": frozenset({"topic", "agenda", "guidance_points", "concerns_to_address", "desired_outcome"}),
	"MEETING": frozenset({"purpose", "agenda", "attendees_hint", "prep_checklist", "desired_outcome"}),
	"EVENT_INVITE": frozenset({"event_ref", "why_relevant", "invite_message", "follow_up_step"}),
	"CAMPUS_VISIT": frozenset({"visit_goal", "itinerary_points", "logistics_notes", "who_to_involve", "desired_outcome"}),
	"DOCUMENT_REQUEST": frozenset(
		{"missing_documents", "deadline", "request_message", "consequence_if_missing", "follow_up_step"}
	),
	"APPLICATION_SUPPORT": frozenset({"blocking_steps", "support_actions", "deadline", "desired_outcome"}),
	"PARENT_CONTACT": frozenset({"parent_ref", "reason", "talking_points", "sensitivities", "desired_outcome", "next_step"}),
	"HANDOFF": frozenset({"to_role", "reason", "context_summary", "open_items", "expected_response_time"}),
}


def _validate_package_seed(seed: dict | None, action_type: str | None) -> None:
	"""Log — never reject — a package_seed whose keys drift from its type.

	The Action writer treats package content as opaque; this only surfaces a
	crm-agents / Frappe contract drift in the logs so it is caught before the
	dashboard renders a half-populated card.
	"""
	if not isinstance(seed, dict) or not seed or not action_type:
		return
	allowed = _PACKAGE_ENVELOPE_KEYS | _PACKAGE_FIELD_SETS.get(action_type, frozenset())
	unknown = sorted(k for k in seed if k not in allowed)
	if unknown:
		frappe.logger("crm.decision").warning(
			f"package_seed keys not in the {action_type} contract: {unknown}"
		)


def _insert_bundle_action(*, student, contact, candidate, current_revision, rank, base_idempotency_key, base_stage_key, producer_identity, payload_digest, writer_epoch, recommendation=None, nba_action=None, rationale=None):
	from crm.fcrm.action_type_catalog import canonicalize_action_type
	from crm.fcrm.action_type_registry import is_available_action_type
	from crm.services.sales_action_policy import require_parent_contact_authority

	action_type = canonicalize_action_type(candidate.get("action_type"))
	disposition = candidate.get("disposition")
	if disposition not in {"ACT", "MONITOR", "NURTURE"} or (disposition == "ACT") != bool(action_type):
		frappe.throw(_("Invalid v2 disposition/action combination."), frappe.ValidationError)
	if action_type and not is_available_action_type(action_type):
		frappe.throw(_("Unsupported v2 action type."), frappe.ValidationError)
	require_parent_contact_authority(action_type, student)
	doc = {
		"doctype": "CRM Action Item",
		"student": student,
		"contact": contact,
		"recommendation": recommendation,
		"origin": "ai",
		"plan_rank": rank,
		"source_context_revision": current_revision,
		"disposition": disposition,
		"action": nba_action or action_type,
		"action_type": action_category(action_type),
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
	_validate_package_seed(candidate.get("package_seed"), action_type)
	doc.update(_plan_rank_defaults(rank))
	return frappe.get_doc(doc).insert(ignore_permissions=True)


def write_canonical_action_bundle(
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
	_require_action_writer()
	_require_legacy_generation_epoch()
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
		"CRM Action Item",
		{"student": student, "source_stage_key": f"{base_stage_key}:r1"},
		["name", "payload_digest"],
		as_dict=True,
	)
	if existing:
		if existing.payload_digest != payload_digest:
			frappe.throw(_("Bundle idempotency key was reused with a different payload."), frappe.ValidationError)
		rows = frappe.get_all(
			"CRM Action Item",
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
		"SELECT name, state FROM `tabCRM Action Item` WHERE student = %s AND current_slot = 'CURRENT' FOR UPDATE",
		(student,),
		as_dict=True,
	)
	if current:
		stale = frappe.get_doc("CRM Action Item", current[0].name)
		previous_flag = getattr(frappe.flags, "crm_action_command", False)
		frappe.flags.crm_action_command = True
		try:
			if str(stale.state) in {"accepted", "in-progress", "requires-review"}:
				stale.requires_review = 1
				stale.review_revision = current_revision
				stale.state = "requires-review"
				stale.save(ignore_permissions=True)
				return {"status": "requires_review", "action": stale.name}
			if str(stale.state) not in CRMActionItem.TERMINAL:
				stale.state = "superseded"
			stale.current_slot = None
			stale.save(ignore_permissions=True)
			from crm.fcrm.nba import sync_nba_recommendation_for_action
			sync_nba_recommendation_for_action(stale)
		finally:
			frappe.flags.crm_action_command = previous_flag

	contact = frappe.db.get_value("CRM Contact", {"student": student}, "name")
	from crm.fcrm.nba import ensure_nba_recommendation
	nba_recommendations = {}
	for rank, candidate in enumerate(candidates, start=1):
		nba_recommendations[rank] = ensure_nba_recommendation(
			student=student,
			action_type=candidate.get("action_type"),
			objective=str(candidate.get("objective") or "")[:500],
			evidence=candidate.get("evidence_refs", []),
			priority=str(candidate.get("priority") or _plan_rank_defaults(rank)["priority"]),
			due_at=candidate.get("due_at"),
			expires_at=candidate.get("expires_at"),
			owner=_default_action_owner(student),
			trigger=candidate.get("trigger") or base_stage_key,
			timing_policy=candidate.get("timing_policy"),
			confidence=candidate.get("confidence"),
			expected_impact=candidate.get("expected_impact"),
			model=candidate.get("model"),
			model_version=candidate.get("model_version"),
		)
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
			recommendation=nba_recommendations[rank].name if nba_recommendations[rank] else None,
			nba_action=nba_recommendations[rank].get("action") if nba_recommendations[rank] else None,
			rationale=rationale_by_type.get(candidate.get("action_type")),
		)
		inserted.append({"name": task.name, "plan_rank": rank})
	return {"status": "completed", "idempotent": False, "actions": inserted}


def _call(fn, **kwargs):
	# Frappe may include the routed RPC command in adapters that accept
	# ``**kwargs``. It is transport metadata, not part of the decision payload.
	kwargs.pop("cmd", None)
	try:
		return fn(**kwargs)
	except StudentDecisionError as exc:
		# Keep the stable domain code available to API clients. Frappe still
		# serializes the exception for backwards compatibility, but clients
		# should not need to parse that human-oriented string.
		try:
			if isinstance(getattr(frappe.local, "response", None), dict):
				frappe.local.response["error"] = {
					"code": exc.code,
					"message": str(exc),
				}
		except (AttributeError, TypeError):
			pass
		exc_type = frappe.PermissionError if exc.code in {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE", "CONTRACT_UNAVAILABLE", "OUTBOX_DISABLED"} else frappe.ValidationError
		frappe.throw(str(exc), exc_type)


def _decide_by_name(name: str, **kwargs):
	"""Dispatch to the V2 task-native command when `name` names a CRM Student
	Task; CRM Recommendation only ever holds pre-cutover historical rows."""
	if frappe.db.exists("CRM Action Item", name):
		fn = _decide_student_task
		kwargs.pop("operation", None)
		kwargs.pop("delta", None)
	else:
		fn = _decide_recommendation
	result = _call(fn, name=name, **kwargs)
	result.setdefault("name", result.get("recommendation") or result.get("action"))
	return result


@frappe.whitelist(methods=["POST"])
def transition_recommendation(name: str, expected_revision: str, status: str | None = None, decision_reason: str | None = None, **kwargs):
	"""Apply a Recommendation decision through the canonical command service."""
	result = _call(
		_decide_recommendation,
		name=name,
		expected_revision=expected_revision,
		status=status,
		operation=kwargs.get("operation"),
		delta=kwargs.get("delta"),
		decision_reason=decision_reason,
		due_at=kwargs.get("due_at"),
		assignee_staff=kwargs.get("assignee_staff"),
		revisit_at=kwargs.get("revisit_at"),
		defer_kind=kwargs.get("defer_kind"),
		idempotency_key=kwargs.get("idempotency_key") or f"recommendation-{name}-{status}",
		correlation_id=kwargs.get("correlation_id") or f"recommendation-{name}",
		expected_modified=kwargs.get("expected_modified"),
	)
	if result.get("recommendation") is not None:
		result.setdefault("name", result["recommendation"])
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
def claim_current_action(**kwargs):
	"""Claim the Student's current queue Action for the calling Sale.

	Not a wrapper over the decision command: it locks the Student row, widens
	care scope to the caller, and re-verifies the current slot under that lock.
	"""
	kwargs.pop("_internal_service", None)
	return _call(_claim_current_action, **kwargs)


@frappe.whitelist(methods=["POST"])
def reassign_action(**kwargs):
	kwargs.pop("_internal_service", None)
	return _call(_reassign_action, **kwargs)


@frappe.whitelist()
def get_action(name: str) -> dict:
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	doc = frappe.get_doc("CRM Action Item", name)
	if not doc.has_permission("read"):
		frappe.throw("You do not have permission to view this Action.", frappe.PermissionError)
	return {"name": doc.name, "student": doc.student, "contact": doc.get("contact"), "action": doc.get("action"), "action_type": doc.action_type, "status": doc.get("execution_status") or doc.state, "revision": doc.get("action_revision") or 1}
