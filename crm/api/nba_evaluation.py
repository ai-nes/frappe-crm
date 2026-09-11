"""Service-only boundary that assembles the current NBA Evaluation input envelope.

The pure shaping and digest binding live in ``crm.fcrm.nba_evaluation_input``
so they stay testable without a bench. This module gathers the live projection,
shapes it to the shared golden-fixture contract, and exposes one whitelisted
entry point restricted to the crm-agents service identity. Nothing here
persists a row or triggers an evaluation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import frappe

from crm.api.student_decision_context import _projection, _require_agent_identity
from crm.fcrm import nba_policy
from crm.fcrm.action_type_catalog import action_category
from crm.fcrm.nba_canonical import canonical_digest
from crm.fcrm.nba_evaluation_input import CONTRACT_VERSION, assemble_evaluation_input, input_digest
from crm.fcrm.nba_timing import feasible_timing_domain, slot_bounds
from crm.services.action_outcome import (
	ACTION_EFFECT_OVERRIDES,
	CATEGORY_OUTCOME_EFFECTS,
	CONTACT_ATTEMPT_FAILURE_VALUE,
	CONTACT_ATTEMPT_RESET_VALUE,
	DECISION_STATUS_REOPEN_TRIGGERS,
	DIMENSION_REDUCERS,
	derive_decision_effects,
)
from crm.services.intelligence_refs import build_outcome_ref, build_subject_ref

# Dimensions that don't persist across unrelated intervening outcomes: only
# the single most recent completed action's own effects can set them. If that
# newest action didn't touch the dimension, it resets to unknown/none even if
# an older action set it -- see DIMENSION_REDUCERS for why (a stale
# "please call back" must not stay sticky forever once newer, unrelated work
# has happened since). decision_status is handled separately below -- it has
# per-value lifecycle semantics, not one uniform rule.
_RESET_TO_NEWEST_ROW_DIMENSIONS = frozenset(
	dim for dim, reducer in DIMENSION_REDUCERS.items() if reducer == "latest_or_reset"
)

# Cost/risk/effort bands have no CRM Action source column yet. The wire contract
# requires the keys, so they are emitted as "unknown" and the action carries
# `metadata_state: "provisional"` so a consumer never mistakes a synthesized
# value for a governed one. A later phase sources these from the catalog.
_UNKNOWN_BAND = "unknown"

__all__ = [
	"CONTRACT_VERSION",
	"assemble_evaluation_input",
	"build_nba_evaluation_input",
	"get_nba_evaluation_input",
	"input_digest",
]

_DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh"


# Durable dimension-scoped history, deliberately not the UI-facing
# ``recent_actions`` projection (hard-limited to the last 5 actions of any
# type -- too narrow for a dimension like interest_disposition to survive
# unrelated actions recorded afterwards).
#
# Each dimension is resolved against only the outcome history that can
# actually affect it (its own candidate outcome-code set), not one shared
# window: a ``latest`` dimension query keeps paging, keyset-ordered on
# ``(completed_at, name)``, until it either finds the newest affecting row or
# genuinely exhausts the student's matching history -- never on a fixed
# multi-dimension row budget that could silently drop a closing signal placed
# beyond it. ``_DIMENSION_QUERY_BUDGET`` is a per-dimension safety valve
# against a pathological history (e.g. thousands of rows sharing an outcome
# code that a category mismatch keeps rejecting); hitting it marks that one
# dimension's ``coverage`` "incomplete" instead of silently returning a
# partial read as if it were authoritative.
_DIMENSION_PAGE_SIZE = 50
_DIMENSION_QUERY_BUDGET = 500

# ``latest`` dimensions persist until an older row is found that set them.
# Derived from the reducer table so a new ``latest`` dimension is covered
# automatically.
_LATEST_PERSIST_DIMENSIONS = frozenset(
	dim for dim, reducer in DIMENSION_REDUCERS.items() if reducer == "latest"
)


_ACTION_OUTCOME_TYPE = "action_execution"


def _immutable_outcome_refs_for_tasks(task_names: list[str]) -> dict[str, dict]:
	"""Batch-resolve each task's immutable ``CRM Action Outcome``, if any.

	A task with no linked ``CRM Action Execution``, or an execution with no
	captured outcome yet (still in flight), is simply absent from the result --
	the caller falls back to the legacy Task-only provenance for that row.
	Two queries regardless of batch size, scoped to one page of tasks at a time
	by the caller.
	"""
	if not task_names:
		return {}
	executions = frappe.get_all(
		"CRM Action Execution",
		filters={"task": ["in", task_names]},
		fields=["name", "task", "recommendation"],
		ignore_permissions=True,
	)
	if not executions:
		return {}
	execution_by_name = {row["name"]: row for row in executions}
	outcomes = frappe.get_all(
		"CRM Action Outcome",
		filters={"execution": ["in", list(execution_by_name)], "outcome_type": _ACTION_OUTCOME_TYPE},
		fields=["name", "execution", "outcome_value", "captured_at"],
		ignore_permissions=True,
	)
	refs: dict[str, dict] = {}
	for outcome in outcomes:
		execution = execution_by_name.get(outcome["execution"])
		if not execution or not execution.get("task"):
			continue
		refs[execution["task"]] = {
			"outcome_name": outcome["name"],
			"execution": outcome["execution"],
			"recommendation": execution.get("recommendation"),
			"outcome_value": outcome.get("outcome_value"),
		}
	return refs


def _effect_provenance(
	outcome_code: str,
	action_ref: str | None,
	occurred_at: str | None,
	*,
	student: str,
	task: str | None,
	immutable_ref: dict | None,
) -> dict:
	"""Drill-down/time-check metadata for one folded effect: which recorded
	outcome shaped the dimension and when (authority time). ``action_ref`` is
	the CRM Action link, never the category fallback -- a drill-down resolves it.

	When the completing task has a linked immutable ``CRM Action Outcome``,
	provenance carries a resolvable ``outcome_ref`` (``verified``) instead of
	only the synthesized action+code pair. Otherwise (no ``CRM Action
	Execution``/``CRM Action Outcome`` row for this task -- a legacy or
	not-yet-executed completion) it is tagged ``legacy_task`` so a consumer
	never mistakes it for a verified outcome.
	"""
	source: dict = {"outcome_code": outcome_code}
	if action_ref:
		source["action"] = action_ref
	provenance: dict = {"source_outcome": source}
	if occurred_at:
		provenance["occurred_at"] = occurred_at
	if immutable_ref:
		provenance["source_kind"] = "verified_outcome"
		provenance["outcome_ref"] = build_outcome_ref(
			outcome_id=immutable_ref["outcome_name"],
			subject=build_subject_ref("student", student, str(frappe.local.site or "frappe")),
			kind="verified_outcome",
			status=str(immutable_ref.get("outcome_value") or outcome_code),
			source_revision=immutable_ref["execution"],
			decision_id=immutable_ref.get("recommendation"),
			verified=True,
		)
	elif task:
		provenance["source_kind"] = "legacy_task"
		provenance["task"] = task
	return provenance


def _dimension_codes(dimension: str) -> frozenset[str]:
	"""Every outcome_code that can *ever* produce an effect on ``dimension``,
	across every action category and per-action override -- used to scope the
	SQL candidate set. A row whose code is in this set is not guaranteed to
	affect the dimension (the same code means different things per category);
	the caller still confirms with ``derive_decision_effects`` before
	accepting it, and simply keeps paging past a false match.
	"""
	codes: set[str] = set()
	for table in (*CATEGORY_OUTCOME_EFFECTS.values(), *ACTION_EFFECT_OVERRIDES.values()):
		for code, effects in table.items():
			if any(effect.dimension == dimension for effect in effects):
				codes.add(code)
	return frozenset(codes)


def _keyset_completed_rows(
	student: str, *, codes: frozenset[str] | None, after: tuple | None, limit: int = _DIMENSION_PAGE_SIZE
) -> list[dict]:
	"""One page of completed ``CRM Action Item`` rows for ``student``, newest
	first, keyset-paginated on ``(completed_at, name)``.

	Keyset (not OFFSET) pagination: a page boundary depends only on the last
	row already seen, never on a shifting row count, so it can't repeat or
	skip a row if history changes between pages. ``codes`` narrows the SQL
	``WHERE`` to one dimension's candidate outcome codes when given (``None``
	means "any completed row", used for the single newest-row probes).
	"""
	if codes is not None and not codes:
		return []
	conditions = ["student=%(student)s", "execution_status='completed'"]
	values: dict = {"student": student, "limit": limit}
	if codes is not None:
		conditions.append("outcome_code in %(codes)s")
		values["codes"] = tuple(codes)
	if after is not None:
		after_at, after_name = after
		values["after_name"] = after_name
		if after_at is None:
			conditions.append("(completed_at is null and name < %(after_name)s)")
		else:
			values["after_at"] = after_at
			conditions.append(
				"(completed_at < %(after_at)s"
				" or (completed_at = %(after_at)s and name < %(after_name)s)"
				" or completed_at is null)"
			)
	where = " and ".join(conditions)
	return frappe.db.sql(
		f"""
		select name, action, action_type, outcome_code, revisit_at, completed_at
		from `tabCRM Action Item`
		where {where}
		order by completed_at desc, name desc
		limit %(limit)s
		""",
		values,
		as_dict=True,
	)


def _dimension_payload(effect, row: dict, student: str) -> dict:
	task = row.get("name")
	action_ref = row.get("action") or None
	occurred_at = str(row["completed_at"]) if row.get("completed_at") else None
	immutable_ref = _immutable_outcome_refs_for_tasks([task]).get(task) if task else None
	return {
		"value": effect.value,
		**_effect_provenance(
			row.get("outcome_code"), action_ref, occurred_at, student=student, task=task, immutable_ref=immutable_ref
		),
	}


def _resolve_latest_dimension(student: str, dimension: str) -> tuple[dict | None, str]:
	"""Newest row whose outcome actually affects ``dimension``, paging through
	only that dimension's candidate outcome codes until found or the
	student's matching history is genuinely exhausted.

	Returns ``(payload, coverage)``: ``coverage`` is ``"known"`` once either a
	match was found or an empty page proved there is nothing left to find,
	and ``"incomplete"`` only if the per-dimension query budget ran out first
	-- a real "we could not confirm" state, never presented as an authoritative
	absence.
	"""
	codes = _dimension_codes(dimension)
	after = None
	examined = 0
	while examined < _DIMENSION_QUERY_BUDGET:
		page = _keyset_completed_rows(student, codes=codes, after=after)
		if not page:
			return None, "known"
		for row in page:
			examined += 1
			action_code = row.get("action") or row.get("action_type")
			effect = next(
				(e for e in derive_decision_effects(action_code, row.get("outcome_code")) if e.dimension == dimension),
				None,
			)
			if effect is not None:
				return _dimension_payload(effect, row, student), "known"
		after = (page[-1].get("completed_at"), page[-1]["name"])
	return None, "incomplete"


def _resolve_follow_up(student: str, newest_row: dict | None) -> tuple[dict | None, str]:
	"""``follow_up`` only ever comes from the single most recent completed
	action -- a stale "please call back" must not stay sticky forever once
	newer, unrelated work has happened since.
	"""
	if not newest_row:
		return None, "known"
	action_code = newest_row.get("action") or newest_row.get("action_type")
	effect = next(
		(e for e in derive_decision_effects(action_code, newest_row.get("outcome_code")) if e.dimension == "follow_up"),
		None,
	)
	if effect is None:
		return None, "known"
	payload = _dimension_payload(effect, newest_row, student)
	if newest_row.get("revisit_at"):
		payload["revisit_at"] = str(newest_row["revisit_at"])
	return payload, "known"


def _resolve_decision_status(student: str, newest_row: dict | None) -> tuple[dict | None, str]:
	"""decision_status lifecycle: "pending" only from the single most recent
	completed action (checked via ``newest_row``, shared with ``follow_up``);
	"not_ready"/"lost" persist like a ``latest`` dimension but are cleared by a
	more-recent reopening outcome (``DECISION_STATUS_REOPEN_TRIGGERS``), so the
	scan tracks every reopen trigger it passes before reaching the blocked value.
	"""
	if newest_row:
		action_code = newest_row.get("action") or newest_row.get("action_type")
		pending = next(
			(
				e
				for e in derive_decision_effects(action_code, newest_row.get("outcome_code"))
				if e.dimension == "decision_status" and e.value == "pending"
			),
			None,
		)
		if pending is not None:
			return _dimension_payload(pending, newest_row, student), "known"
	reopen_codes = {code for codes in DECISION_STATUS_REOPEN_TRIGGERS.values() for code in codes}
	codes = _dimension_codes("decision_status") | reopen_codes
	after = None
	examined = 0
	blocked = {"not_ready": False, "lost": False}
	while examined < _DIMENSION_QUERY_BUDGET:
		page = _keyset_completed_rows(student, codes=codes, after=after)
		if not page:
			return None, "known"
		for row in page:
			examined += 1
			action_code = row.get("action") or row.get("action_type")
			outcome_code = row.get("outcome_code")
			effects = derive_decision_effects(action_code, outcome_code)
			decision_effect = next((e for e in effects if e.dimension == "decision_status"), None)
			if decision_effect is not None:
				if decision_effect.value in ("not_ready", "lost"):
					if blocked[decision_effect.value]:
						return None, "known"
					return _dimension_payload(decision_effect, row, student), "known"
				continue
			for value, reopen_outcomes in DECISION_STATUS_REOPEN_TRIGGERS.items():
				if outcome_code in reopen_outcomes:
					blocked[value] = True
		after = (page[-1].get("completed_at"), page[-1]["name"])
	return None, "incomplete"


def _resolve_contact_attempt_signal(student: str) -> tuple[dict, str]:
	"""Count a *consecutive* run of "failed" contact effects, newest first,
	stopping (and not counting) as soon as a "succeeded" effect is seen.
	"""
	codes = _dimension_codes("contact_attempt_signal")
	after = None
	examined = 0
	failures = 0
	last_failure_at: str | None = None
	seen_failure = False

	def _payload(coverage: str) -> dict:
		signal: dict = {"consecutive_failures": failures}
		if last_failure_at:
			signal["occurred_at"] = last_failure_at
		return signal

	while examined < _DIMENSION_QUERY_BUDGET:
		page = _keyset_completed_rows(student, codes=codes, after=after)
		if not page:
			return _payload("known"), "known"
		for row in page:
			examined += 1
			action_code = row.get("action") or row.get("action_type")
			effect = next(
				(
					e
					for e in derive_decision_effects(action_code, row.get("outcome_code"))
					if e.dimension == "contact_attempt_signal"
				),
				None,
			)
			if effect is None:
				continue
			if effect.value == CONTACT_ATTEMPT_RESET_VALUE:
				return _payload("known"), "known"
			if effect.value == CONTACT_ATTEMPT_FAILURE_VALUE:
				failures += 1
				if not seen_failure:
					# Lock onto the newest failure row even when its
					# ``completed_at`` is NULL, so an older failure's time
					# never masquerades as the most recent one.
					seen_failure = True
					last_failure_at = str(row["completed_at"]) if row.get("completed_at") else None
		after = (page[-1].get("completed_at"), page[-1]["name"])
	return _payload("incomplete"), "incomplete"


def _decision_effect_signals(student: str) -> dict:
	"""Resolve Decision Effects per dimension, each against only the outcome
	history that can actually affect it (see ``crm.services.action_outcome.
	DIMENSION_REDUCERS`` for the reducer each dimension uses). A dimension the
	per-dimension query budget could not confirm is marked ``coverage:
	"incomplete"`` under ``result["coverage"]`` -- the kernel must treat that
	as unknown, never as "no signal", so a candidate depending on it can
	abstain/drop rather than act on a missing-data assumption.
	"""
	result: dict = {}
	coverage: dict = {}
	newest_rows = _keyset_completed_rows(student, codes=None, after=None, limit=1)
	newest_row = newest_rows[0] if newest_rows else None

	for dimension in _LATEST_PERSIST_DIMENSIONS:
		payload, status = _resolve_latest_dimension(student, dimension)
		if payload is not None:
			result[dimension] = payload
		coverage[dimension] = status

	follow_up_payload, follow_up_status = _resolve_follow_up(student, newest_row)
	if follow_up_payload is not None:
		result["follow_up"] = follow_up_payload
	coverage["follow_up"] = follow_up_status

	decision_status_payload, decision_status_status = _resolve_decision_status(student, newest_row)
	if decision_status_payload is not None:
		result["decision_status"] = decision_status_payload
	coverage["decision_status"] = decision_status_status

	contact_payload, contact_status = _resolve_contact_attempt_signal(student)
	result["contact_attempt_signal"] = contact_payload
	coverage["contact_attempt_signal"] = contact_status

	result["coverage"] = coverage
	return result


def _shape_student(projection: Mapping, *, now: datetime, timezone: str) -> dict:
	return {
		"student_id": projection.get("student_id"),
		"context_revision": int(projection.get("returned_revision") or 0),
		"context_digest": projection.get("snapshot_hash"),
		"observed_at": now.isoformat(),
		"timezone": timezone,
	}


def _wire_temporal(value: object, *, timezone: str) -> object:
	"""Serialize Frappe temporal values with an explicit timezone for AI facts."""
	if not isinstance(value, (date, datetime)):
		return value
	if isinstance(value, datetime) and value.tzinfo is None:
		value = value.replace(tzinfo=ZoneInfo(timezone))
	return value.isoformat()


def _shape_context(projection: Mapping, *, student: str, now: datetime, timezone: str) -> dict:
	intent = projection.get("intent") or {}
	interaction = projection.get("interaction") or {}
	assessment = projection.get("assessment") or {}
	application = projection.get("application") or {}
	score = projection.get("score") or {}
	academic = projection.get("academic") or {}
	interaction_at = interaction.get("at")
	interaction_at = _wire_temporal(interaction_at, timezone=timezone)
	application_deadline = application.get("deadline")
	application_deadline = _wire_temporal(application_deadline, timezone=timezone)
	academic_signal = {
		"gpa": academic.get("gpa"),
		"quality": academic.get("quality") or "unknown",
		"source_revision": academic.get("source_revision") or "unknown",
	}
	if academic.get("quality") == "current" and academic.get("evidence_ref"):
		academic_signal["evidence_ref"] = str(academic["evidence_ref"])
	consent = projection.get("is_opted_out")
	consent_value = None if consent is None else bool(consent)
	return {
		"student_stage": projection.get("student_stage"),
		"student": {
			"stage": projection.get("student_stage"),
			"is_opted_out": consent_value,
			"email_bounced": bool(projection.get("email_bounced")),
		},
		"intent": {"type": intent.get("type"), "polarity": intent.get("polarity")},
		"engagement": {
			"state": interaction.get("outcome") or "unknown",
			"last_contact_days": interaction.get("days_since"),
		},
		"interaction": {"at": interaction_at},
		"application_state": {
			"status": application.get("status"),
			"document_total": application.get("document_total"),
			"document_completed": application.get("document_completed"),
			"deadline": application_deadline,
			"completeness": application.get("completeness") or "unknown",
			"missing": list(application.get("missing") or []),
			"missing_count": int(application.get("missing_count") or 0),
			"source_revision": application.get("source_revision") or "unknown",
		},
		"activity": {"last_contact_at": interaction_at},
		"score": {"source_revision": score.get("current_revision")},
		"academic": academic_signal,
		"blockers": [assessment["primary_barrier"]] if assessment.get("primary_barrier") else [],
		"deadlines": (
			[
				{
					"kind": "application",
					"at": (now + timedelta(days=int(projection["days_to_deadline"]))).isoformat(),
				}
			]
			if projection.get("days_to_deadline") is not None
			else []
		),
		"contactability": {
			"consent": bool((projection.get("contactability") or {}).get("consent")),
			"channels": list((projection.get("contactability") or {}).get("channels") or []),
			"recipient_bound": (projection.get("contactability") or {}).get("recipient_bound") is not False,
			"is_opted_out": consent_value,
			"email_bounced": bool(projection.get("email_bounced")),
		},
		"parent_authority": {
			"valid": bool((projection.get("parent_authority") or {}).get("valid")),
		},
		"work_in_flight": [row.get("action_type") for row in projection.get("recent_actions") or []],
		# Decision Effects folded per dimension over durable outcome history --
		# see `_decision_effect_signals`. Structured input for the kernel's
		# opportunity suppression, not a raw outcome_code passthrough.
		"decision_effects": _decision_effect_signals(student),
		# Owner capacity has no approved scenario. Preserve the member for
		# historical replay while emitting explicit unknown rather than inferring
		# workload from action rows or assignments.
		"owner_capacity": {"owner": None, "open_tasks": None},
		"evidence_refs": list(projection.get("evidence_refs") or []),
		"signal_quality": {
			"freshness": score.get("freshness") or "unknown",
			"missingness": [],
			"conflicts": [],
		},
	}


def _require_hex64(value: object, label: str) -> str:
	"""Return ``value`` only when it is a real 64-hex digest; fail closed otherwise.

	The boundary never fabricates a digest to satisfy the contract shape: a
	missing or malformed digest means the control plane has not produced the
	revision identity yet, and a synthesized value would silently break any
	consumer that re-derives it.
	"""
	if isinstance(value, str) and len(value) == 64:
		try:
			int(value, 16)
		except ValueError:
			pass
		else:
			return value
	frappe.throw(f"NBA control plane has no valid {label}; run the schema migration first.")


def _timing_domain_for_action(allowed_time_slots: object, timezone: str) -> dict:
	"""Translate ``CRM Action.allowed_time_slots`` into a normalized timing domain.

	An action with no configured slots stays unconstrained (``{}``), matching
	current behaviour: the kernel schedules it as soon as evaluated.
	"""
	windows = []
	for slot in allowed_time_slots or []:
		try:
			start, end = slot_bounds(str(slot))
		except ValueError:
			continue
		windows.append(
			{
				"code": str(slot),
				"from": f"{start.hour:02d}:{start.minute:02d}",
				"to": f"{end.hour:02d}:{end.minute:02d}",
			}
		)
	if not windows:
		return {}
	return {"timezone": timezone, "allowed_windows": windows}


def _shape_eligible_action_set(eligible: Mapping, *, timezone: str) -> dict:
	actions = []
	wire_actions = []
	for action in eligible.get("actions") or []:
		code = action.get("code")
		channel = action.get("default_channel")
		action_id = nba_policy.wire_action_id(code)
		revision = int(action.get("revision") or 1)
		digest = _require_hex64(action.get("digest"), f"action_digest for {action_id}")
		timing_domain = _timing_domain_for_action(action.get("allowed_time_slots"), timezone)
		runtime_digest = canonical_digest({"normalized_timing_domain": timing_domain})
		wire_actions.append(
			{
				"action_id": action_id,
				"revision": revision,
				"digest": digest,
				"action_runtime_digest": runtime_digest,
			}
		)
		actions.append(
			{
				"action_id": action_id,
				"action_revision": revision,
				"action_digest": digest,
				"action_code": code,
				"group": (action.get("category") or action_category(code) or "general").lower(),
				"purpose": action.get("purpose") or code,
				"addresses_opportunities": list(action.get("addresses_opportunities") or []),
				"allowed_channels": [channel] if channel not in (None, "NONE") else [],
				"allowed_actors": list(action.get("allowed_actors") or []),
				"addresses_needs": list(action.get("addresses_needs") or []),
				"desired_outcomes": list(action.get("desired_outcomes") or []),
				"collects_information": bool(action.get("collects_information")),
				"readiness_target": action.get("readiness_target") or "none",
				"execution_parameter_schema": {},
				"default_parameters": {},
				"hard_constraints": {
					"requires_parent_authority": bool(
						action.get("requires_parent_authority") or action.get("category") == "PARENT"
					),
					"academic": dict(action.get("academic_constraint") or {}),
				},
				"normalized_timing_domain": timing_domain,
				"action_runtime_digest": runtime_digest,
				"metadata_state": "provisional",
				"cost_band": _UNKNOWN_BAND,
				"risk_band": _UNKNOWN_BAND,
				"effort_band": _UNKNOWN_BAND,
				"conflict_keys": [f"action:{code}"],
			}
		)
	semantic_projection = {
		action["action_id"]: {
			field: action[field]
			for field in (
				"addresses_needs",
				"desired_outcomes",
				"collects_information",
				"readiness_target",
			)
		}
		for action in actions
	}
	semantic_digest = canonical_digest(
		{key: semantic_projection[key] for key in sorted(semantic_projection)}
	)
	set_digest = nba_policy.eligible_set_digest(wire_actions)
	return {
		"set_revision": int(eligible.get("revision") or 0),
		"set_digest": set_digest,
		"semantic_digest": semantic_digest,
		"actions": actions,
		"exclusions": sorted(
			list(eligible.get("exclusions") or []),
			key=lambda item: (str(item.get("action") or ""), str(item.get("reason") or "")),
		),
	}


def _shape_policies(
	decision: Mapping,
	eligible: Mapping,
	eligible_set: Mapping,
	timing_digest: str,
	engine_revision: str,
	*,
	rule_catalog: Mapping[str, Any] | None = None,
) -> dict:
	revision = eligible.get("revision") or 0
	ruleset_identity = {}
	if isinstance(rule_catalog, Mapping):
		version = rule_catalog.get("rule_version")
		digest = rule_catalog.get("ruleset_digest")
		if version and digest:
			ruleset_identity = {
				"rule_version": str(version),
				"rule_version_digest": str(digest),
				"ruleset_digest": str(digest),
			}
	if not ruleset_identity:
		frappe.throw("CRM Rule Settings has no complete active snapshot.", frappe.ValidationError)
	return {
		"library_revision": f"action-library-r{revision}",
		"library_digest": canonical_digest({
			"action_set_digest": eligible_set["set_digest"],
			"semantic_digest": eligible_set["semantic_digest"],
		}),
		"eligibility_revision": "eligibility-reason-codes",
		# The eligibility contract the engine binds is the reason-code vocabulary,
		# not one student's exclusion list; that list is per-evaluation data.
		"eligibility_digest": canonical_digest({"reason_codes": sorted(nba_policy.EXCLUSION_REASONS)}),
		"decision_revision": str(
			(decision.get("decision_policy") or {}).get("revision")
			or f"nba-decision-policy-r{decision.get('policy_revision') or 1}"
		),
		"decision_digest": _require_hex64(decision.get("policy_digest"), "decision_digest"),
		"decision_policy": dict(decision.get("decision_policy") or {}),
		"timing_revisions": [],
		"timing_digest": _require_hex64(timing_digest, "timing_digest"),
		"semantic_digest": eligible_set["semantic_digest"],
		# Technical observability label only. It is not a behaviour selector.
		"engine_revision": engine_revision,
		# Durable NBA inputs carry only the immutable ruleset identity. The
		# complete catalog is loaded by crm-agents through its service provider,
		# so an embedded catalog cannot become a second runtime source.
		"ruleset_identity": ruleset_identity,
	}


def _active_rule_catalog(
	feature_scope: str,
	*,
	version: str | None = None,
	expected_digest: str | None = None,
	service_authorized: bool = False,
) -> dict:
	"""Read the complete snapshot selected by CRM Rule Settings."""
	from crm.api.rule_engine import (
		active_rule_catalog_internal,
		get_active_rule_catalog,
		get_rule_catalog,
	)

	if expected_digest:
		if not version:
			frappe.throw("Immutable CRM Rule lookup requires a rule version.", frappe.ValidationError)
		return get_rule_catalog(version=version, expected_digest=expected_digest)
	# Delegated request creation is already authorized against the Student, but
	# must not expose the complete catalog through a service-only endpoint. Use
	# the same authoritative pointer internally; service workers continue to
	# use the permission-checked catalog API.
	return get_active_rule_catalog(feature_scope=feature_scope) if service_authorized else active_rule_catalog_internal(feature_scope)


_DEFAULT_ENGINE_REVISION = "nba-engine"


def build_nba_evaluation_input(
	student: str,
	*,
	minimum_revision: int = 0,
	actor: str | None = None,
	now: datetime | None = None,
	service_authorized: bool = False,
	engine_revision: str | None = None,
	rule_version: str | None = None,
	ruleset_digest: str | None = None,
) -> dict:
	"""Assemble the current NBA Evaluation input for one student from live data.

	``service_authorized`` must only be set by a caller that has already run
	``_require_agent_identity()``/``_service_only()`` on the current request --
	see ``_projection``'s own docstring for why this bypasses the per-user
	Student read check.

	``engine_revision`` is retained as a technical observability field for the
	public wire contract. It never selects behaviour; every request uses the
	current unversioned engine label.
	"""
	moment = now or frappe.utils.now_datetime()
	timezone = frappe.db.get_single_value("System Settings", "time_zone") or _DEFAULT_TIMEZONE
	resolved_engine_revision = _DEFAULT_ENGINE_REVISION
	rule_catalog = _active_rule_catalog(
		"nba",
		version=rule_version,
		expected_digest=ruleset_digest,
		service_authorized=service_authorized,
	)

	projection = _projection(student, int(minimum_revision), service_authorized=service_authorized, at=moment)
	eligible = nba_policy.eligible_action_set_for_student(
		student,
		actor=actor,
		now=moment,
		service_authorized=service_authorized,
		decision_context=projection,
	)
	decision = nba_policy.get_active_decision_policy()
	timing = feasible_timing_domain({"trigger_type": "relative", "delay_value": 0}, now=moment)

	eligible_set = _shape_eligible_action_set(eligible, timezone=timezone)
	return assemble_evaluation_input(
		_shape_student(projection, now=moment, timezone=timezone),
		_shape_context(projection, student=student, now=moment, timezone=timezone),
		eligible_set,
		_shape_policies(
			decision,
			eligible,
			eligible_set,
			canonical_digest(timing),
			resolved_engine_revision,
			rule_catalog=rule_catalog,
		),
		now=moment,
	)


@frappe.whitelist()
def get_nba_evaluation_input(student: str, minimum_revision: int = 0) -> dict:
	"""Service-identity only. Does not persist or trigger an evaluation.

	Boundary eligibility is catalog-level (effective window, actor roles, enabled
	state) -- not a per-rollout gate -- so there is no rollout-epoch parameter.
	"""
	_require_agent_identity()
	return build_nba_evaluation_input(student, minimum_revision=int(minimum_revision), service_authorized=True)


# --------------------------------------------------------------------------- #
# Durable NBA Evaluation runtime commands (Phase 03).
#
# All are feature-gated by ``crm_nba_evaluation_runtime_enabled`` inside
# ``crm.fcrm.nba_evaluations`` and throw when the runtime is disabled. The
# lifecycle module is imported lazily to avoid a circular import at load time.
# --------------------------------------------------------------------------- #
@frappe.whitelist(methods=["POST"])
def request_nba_evaluation(student: str, idempotency_key: str | None = None, force_reason: str | None = None):
	"""Delegated or service caller: create/reuse one scoped NBA Evaluation run."""
	from crm.fcrm import nba_evaluations
	from crm.fcrm.student_reference import canonical_student

	# The dashboard can send the legacy Lead id (for example, ``ENR-2026-00003``)
	# while the NBA aggregate is stored under the canonical ``CRM Student`` id
	# (for example, ``CRMC-2026-00003``). Resolve it before the existence and
	# row-scope checks so a valid, visible target is not reported as forbidden.
	student = canonical_student(student) or student

	return nba_evaluations.request_nba_evaluation(
		student=student,
		idempotency_key=idempotency_key or frappe.get_request_header("Idempotency-Key"),
		force_reason=force_reason,
	)


@frappe.whitelist(methods=["POST"])
def get_nba_evaluation_execution(evaluation: str):
	"""Service-only generic-signal materialization; never exposes CRM evidence."""
	from crm.fcrm import nba_evaluations

	return nba_evaluations.execution(evaluation)


@frappe.whitelist(methods=["POST"])
def claim_nba_evaluation(evaluation: str, run_generation: int):
	"""Acquire a fenced service-only execution lease before evaluation."""
	from crm.fcrm import nba_evaluations

	return nba_evaluations.claim_nba_evaluation(evaluation=evaluation, run_generation=int(run_generation))


@frappe.whitelist(methods=["POST"])
def nba_evaluation_snapshot(evaluation: str, lease_token: str):
	"""Return the current authoritative evaluation input under an owned lease."""
	from crm.fcrm import nba_evaluations

	return nba_evaluations.snapshot(evaluation=evaluation, lease_token=lease_token)


@frappe.whitelist(methods=["POST"])
def commit_nba_evaluation_result(
	evaluation: str,
	run_generation: int,
	lease_token: str,
	engine_revision: str | None = None,
	run_status: str = "completed",
	disposition: str | None = None,
	reason_codes: object = None,
	result_digest: str | None = None,
	trace_digest: str | None = None,
	revisit_at: str | None = None,
	reevaluation_trigger: str | None = None,
	recommendations: object = None,
	trace_entries: object = None,
	terminal_reason: str | None = None,
	rule_version: str | None = None,
	rule_version_digest: str | None = None,
	ruleset_digest: str | None = None,
	rule_decision: object = None,
):
	"""Fenced terminal settlement that also writes the immutable Recommendation rows."""
	from crm.fcrm import nba_evaluations

	return nba_evaluations.commit_nba_evaluation_result(
		evaluation=evaluation,
		run_generation=int(run_generation),
		lease_token=lease_token,
		engine_revision=engine_revision,
		run_status=run_status,
		disposition=disposition,
		reason_codes=reason_codes,
		result_digest=result_digest,
		trace_digest=trace_digest,
		revisit_at=revisit_at,
		reevaluation_trigger=reevaluation_trigger,
		recommendations=recommendations,
		trace_entries=trace_entries,
		terminal_reason=terminal_reason,
		rule_version=rule_version,
		rule_version_digest=rule_version_digest,
		ruleset_digest=ruleset_digest,
		rule_decision=rule_decision,
	)


@frappe.whitelist(methods=["POST"])
def set_recommendation_rationale(recommendation: str, explanation: object, source: str):
	"""Fenced, idempotent, write-once explanation set on one committed Recommendation.

	Service-only. Called strictly after ``commit_nba_evaluation_result``
	accepted the owning evaluation; never touches score, rank, timing, action
	or disposition. ``explanation`` is the structured, sale-facing work-item
	object (``objective``, ``why_this_action``, ``context``, plus the
	kernel-echoed ``action``). The work item's name lives only once, nested
	under ``action.title``, and is always the action's own catalog display
	name -- never model-authored.
	"""
	from crm.fcrm import nba_evaluations

	return nba_evaluations.set_recommendation_rationale(
		recommendation=recommendation,
		explanation=explanation,
		source=source,
	)


@frappe.whitelist(methods=["POST"])
def settle_nba_evaluation(
	evaluation: str,
	run_generation: int,
	lease_token: str,
	status: str,
	disposition: str | None = None,
	result_digest: str | None = None,
	trace_digest: str | None = None,
	terminal_reason: str | None = None,
	engine_revision_settled: str | None = None,
	recommendation_count: int = 0,
	rule_version: str | None = None,
	rule_version_digest: str | None = None,
	ruleset_digest: str | None = None,
	rule_decision: object = None,
):
	"""Terminal-only, fenced worker settlement with idempotent terminal replay."""
	from crm.fcrm import nba_evaluations

	return nba_evaluations.settle_nba_evaluation(
		evaluation=evaluation,
		run_generation=int(run_generation),
		lease_token=lease_token,
		status=status,
		disposition=disposition,
		result_digest=result_digest,
		trace_digest=trace_digest,
		terminal_reason=terminal_reason,
		engine_revision_settled=engine_revision_settled,
		recommendation_count=int(recommendation_count or 0),
		rule_version=rule_version,
		rule_version_digest=rule_version_digest,
		ruleset_digest=ruleset_digest,
		rule_decision=rule_decision,
	)
