"""Service-only boundary that assembles the NBA Evaluation v1 input envelope.

The pure shaping and digest binding live in ``crm.fcrm.nba_evaluation_input``
so they stay testable without a bench. This module gathers the live projection,
shapes it to the shared golden-fixture contract, and exposes one whitelisted
entry point restricted to the crm-agents service identity. Nothing here
persists a row or triggers an evaluation.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

import frappe

from crm.api.student_decision_context import _projection, _require_agent_identity
from crm.fcrm import nba_policy
from crm.fcrm.action_type_catalog import action_category
from crm.fcrm.nba_canonical import canonical_digest
from crm.fcrm.nba_evaluation_input import CONTRACT_VERSION, assemble_evaluation_input, input_digest
from crm.fcrm.nba_timing import feasible_timing_domain

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


def _shape_student(projection: Mapping, *, now: datetime, timezone: str) -> dict:
	return {
		"student_id": projection.get("student_id"),
		"context_revision": int(projection.get("returned_revision") or 0),
		"context_digest": projection.get("snapshot_hash"),
		"observed_at": now.isoformat(),
		"timezone": timezone,
	}


def _shape_context(projection: Mapping, *, now: datetime) -> dict:
	lifecycle = projection.get("lifecycle") or {}
	intent = projection.get("intent") or {}
	interaction = projection.get("interaction") or {}
	assessment = projection.get("assessment") or {}
	application = projection.get("application") or {}
	score = projection.get("score") or {}
	return {
		"lifecycle": {"stage": lifecycle.get("stage")},
		"intent": {"type": intent.get("type"), "polarity": intent.get("polarity")},
		"engagement": {
			"state": interaction.get("outcome") or "unknown",
			"last_contact_days": interaction.get("days_since"),
		},
		"application_state": {
			"completeness": application.get("completeness") or "unknown",
			"missing": list(application.get("missing") or []),
			"missing_count": int(application.get("missing_count") or 0),
			"source_revision": application.get("source_revision") or "unknown",
		},
		"academic": {
			"gpa": (projection.get("academic") or {}).get("gpa"),
			"quality": (projection.get("academic") or {}).get("quality") or "unknown",
			"source_revision": (projection.get("academic") or {}).get("source_revision") or "unknown",
		},
		"blockers": [assessment["primary_barrier"]] if assessment.get("primary_barrier") else [],
		"deadlines": (
			[
				{
					"kind": "application",
					"at": (now + timedelta(days=int(lifecycle["days_to_deadline"]))).isoformat(),
				}
			]
			if lifecycle.get("days_to_deadline") is not None
			else []
		),
		"contactability": {
			"consent": bool((projection.get("contactability") or {}).get("consent")),
			"channels": list((projection.get("contactability") or {}).get("channels") or []),
			"recipient_bound": (projection.get("contactability") or {}).get("recipient_bound") is not False,
		},
		"parent_authority": {
			"valid": bool((projection.get("parent_authority") or {}).get("valid")),
		},
		"work_in_flight": [row.get("action_type") for row in projection.get("recent_actions") or []],
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


def _shape_eligible_action_set(eligible: Mapping) -> dict:
	actions = []
	wire_actions = []
	for action in eligible.get("actions") or []:
		code = action.get("code")
		channel = action.get("default_channel")
		action_id = nba_policy.wire_action_id(code)
		revision = int(action.get("revision") or 1)
		digest = _require_hex64(action.get("digest"), f"action_digest for {action_id}")
		wire_actions.append({"action_id": action_id, "revision": revision, "digest": digest})
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
				"execution_parameter_schema": {},
				"default_parameters": {},
				"hard_constraints": {
					"requires_parent_authority": bool(
						action.get("requires_parent_authority") or action.get("category") == "PARENT"
					),
					"academic": dict(action.get("academic_constraint") or {}),
				},
				"normalized_timing_domain": {},
				"metadata_state": "provisional",
				"cost_band": _UNKNOWN_BAND,
				"risk_band": _UNKNOWN_BAND,
				"effort_band": _UNKNOWN_BAND,
				"conflict_keys": [f"action:{code}"],
			}
		)
	return {
		"set_revision": int(eligible.get("revision") or 0),
		"set_digest": nba_policy.eligible_set_digest(wire_actions),
		"actions": actions,
	}


def _shape_policies(decision: Mapping, eligible: Mapping, eligible_set: Mapping, timing_digest: str) -> dict:
	revision = eligible.get("revision") or 0
	return {
		"library_revision": f"action-library-r{revision}",
		"library_digest": eligible_set["set_digest"],
		"eligibility_revision": "eligibility-reason-codes-v1",
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
	}


def build_nba_evaluation_input(
	student: str,
	*,
	minimum_revision: int = 0,
	actor: str | None = None,
	now: datetime | None = None,
	service_authorized: bool = False,
) -> dict:
	"""Assemble the NBA Evaluation v1 input for one student from live data.

	``service_authorized`` must only be set by a caller that has already run
	``_require_agent_identity()``/``_service_only()`` on the current request --
	see ``_projection``'s own docstring for why this bypasses the per-user
	Student read check.
	"""
	moment = now or frappe.utils.now_datetime()
	timezone = frappe.db.get_single_value("System Settings", "time_zone") or _DEFAULT_TIMEZONE

	projection = _projection(student, int(minimum_revision), service_authorized=service_authorized)
	eligible = nba_policy.eligible_action_set_for_student(
		student,
		actor=actor,
		now=moment,
		service_authorized=service_authorized,
		decision_context=projection,
	)
	decision = nba_policy.get_active_decision_policy()
	timing = feasible_timing_domain({"trigger_type": "relative", "delay_value": 0}, now=moment)

	eligible_set = _shape_eligible_action_set(eligible)
	return assemble_evaluation_input(
		_shape_student(projection, now=moment, timezone=timezone),
		_shape_context(projection, now=moment),
		eligible_set,
		_shape_policies(decision, eligible, eligible_set, canonical_digest(timing)),
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
	)


@frappe.whitelist(methods=["POST"])
def set_recommendation_rationale(recommendation: str, explanation: object, source: str):
	"""Fenced, idempotent, write-once explanation set on one committed Recommendation.

	Service-only. Called strictly after ``commit_nba_evaluation_result``
	accepted the owning evaluation; never touches score, rank, timing, action
	or disposition. ``explanation`` is the structured six-field grounded
	explanation object (``summary``, ``why_action``, ``why_now``,
	``timing_reason``, ``evidence_summary``, ``uncertainty``,
	``execution_guidance``).
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
	)
