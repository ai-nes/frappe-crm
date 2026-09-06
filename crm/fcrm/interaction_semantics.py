"""Canonical Interaction vocabulary — frozen cross-repo contract.

Byte-identical mapping to crm-agents' `app/contracts/interaction_semantics.py`
(no shared package exists across the two repos). `CONTENT_HASH` freezes the
mapping so an edit to either copy that isn't mirrored to the other fails that
repo's own contract test immediately, without a cross-repo import at test
time. Bump CONTRACT_VERSION (and update CONTENT_HASH in both repos) for any
intentional change, keeping both copies in lockstep.

This module answers Channel / Purpose / Disposition and "is this a direct
admissions touchpoint, or independent evidence?" for the `interaction_type`
(Link to `CRM Interaction Type`) and `outcome` (Select) fields on CRM
Interaction. Its keys are the `CRM Interaction Type` codes that writers now
store directly.
"""

import hashlib
import json
from collections.abc import Mapping

CONTRACT_VERSION = 3

INTERACTION_INTELLIGENCE_CONTRACT_VERSION = "interaction-intelligence-v1"
SILENCE_WINDOW_SECONDS = 15 * 60
SUPPORTED_ANALYSIS_RESULT_STATES = frozenset({"no_intent", "intent_bearing", "unknown", "failed"})

# Mirrored with crm-agents' app/contracts/interaction_semantics.py.  Phase 01
# is intentionally data-only: Frappe remains the evidence owner and existing
# permission checks guard references; no separate evidence service is created.
INTERACTION_INTELLIGENCE_POLICY = {
	"contract_version": INTERACTION_INTELLIGENCE_CONTRACT_VERSION,
	"episode": {
		"silence_window_seconds": SILENCE_WINDOW_SECONDS,
		"late_event": "new_source_revision_and_reanalysis",
		"call": {
			"draft": "evidence_only",
			"final": "seal_and_analyze",
			"correction": "new_source_revision_and_reanalysis",
		},
	},
	"evidence": {
		"owner": "frappe",
		"access": "protected_permission_scoped_reference",
		"raw_content_destinations": "evidence_only",
		"retention": "existing_frappe_lifecycle_no_new_phase_one_mechanism",
	},
	"service_auth": {
		"writer_boundary": "existing_frappe_authenticated_api",
		"scope": "frappe_permission_checks",
		"new_signature_scheme": "not_introduced_in_phase_one",
	},
	"intent": {
		"no_intent": "no_crm_intent",
		"unknown": "needs_review",
		"intent_bearing": "create_crm_intent",
		"eligible_actor_roles": ("student",),
	},
	"term": {
		"semantic_key": "immutable",
		"label": "mutable_display_only",
		"retirement": "retire_without_rewriting_history",
		"enforcement": "phase_two_frappe_schema_migration",
	},
	"compatibility": {
		"supported_versions": (INTERACTION_INTELLIGENCE_CONTRACT_VERSION,),
		"unknown_version": "reject",
		"same_version_additive_fields": "reject_at_boundary",
	},
}

# Non-negotiable: Assignment, consent, campaign attribution, event
# participation, and internal tasks are independent evidence, not
# auto-mirrored interactions. Until the writers in interaction_log.py fully
# canonicalize, these legacy types keep flowing onto CRM Interaction rows at
# the physical layer, so the contract marks them non-direct-touchpoint
# rather than pretending they don't exist there.
INTERACTION_TYPE_MAPPING = {
	"OUTREACH": {
		"channel": "Email",
		"purpose": "Outreach",
		"disposition": "Sent",
		"is_direct_touchpoint": True,
		"evidence_kind": "interaction",
	},
	"MESSAGE_CHATWOOT": {
		"channel": "Chat",
		"purpose": "Conversation",
		"disposition": "Received",
		"is_direct_touchpoint": True,
		"evidence_kind": "interaction",
	},
	"CONNECTED": {
		"channel": "Call",
		"purpose": "Outreach",
		"disposition": "Connected",
		"is_direct_touchpoint": True,
		"evidence_kind": "interaction",
	},
	"COUNSELING": {
		"channel": "Call",
		"purpose": "Counseling",
		"disposition": "Connected",
		"is_direct_touchpoint": True,
		"evidence_kind": "interaction",
	},
	"STAGE_CHANGED": {
		"channel": "System",
		"purpose": "Lifecycle",
		"disposition": "Stage Changed",
		"is_direct_touchpoint": False,
		"evidence_kind": "lifecycle_event",
	},
	"LEAD_ASSIGNED": {
		"channel": "System",
		"purpose": "Lifecycle",
		"disposition": "Assigned",
		"is_direct_touchpoint": False,
		"evidence_kind": "ownership_event",
	},
	"LEAD_REASSIGNED": {
		"channel": "System",
		"purpose": "Lifecycle",
		"disposition": "Reassigned",
		"is_direct_touchpoint": False,
		"evidence_kind": "ownership_event",
	},
	"OPT_OUT": {
		"channel": "System",
		"purpose": "Consent",
		"disposition": "Opted Out",
		"is_direct_touchpoint": False,
		"evidence_kind": "consent_event",
	},
	"OPT_IN": {
		"channel": "System",
		"purpose": "Consent",
		"disposition": "Opted In",
		"is_direct_touchpoint": False,
		"evidence_kind": "consent_event",
	},
	"BOUNCE": {
		"channel": "System",
		"purpose": "Consent",
		"disposition": "Bounced",
		"is_direct_touchpoint": False,
		"evidence_kind": "consent_event",
	},
	"DATA_ERROR": {
		"channel": "System",
		"purpose": "Consent",
		"disposition": "Suppressed",
		"is_direct_touchpoint": False,
		"evidence_kind": "consent_event",
	},
	"REGISTERED": {
		"channel": "Event",
		"purpose": "Event Engagement",
		"disposition": "Registered",
		"is_direct_touchpoint": False,
		"evidence_kind": "event_participation",
	},
	"CHECKED_IN": {
		"channel": "Event",
		"purpose": "Event Engagement",
		"disposition": "Checked-in",
		"is_direct_touchpoint": False,
		"evidence_kind": "event_participation",
	},
	"NO_SHOW": {
		"channel": "Event",
		"purpose": "Event Engagement",
		"disposition": "No-show",
		"is_direct_touchpoint": False,
		"evidence_kind": "event_participation",
	},
	"FEEDBACK": {
		"channel": "Event",
		"purpose": "Event Engagement",
		"disposition": "Feedback Given",
		"is_direct_touchpoint": False,
		"evidence_kind": "event_participation",
	},
	"CAMPAIGN_TOUCHED": {
		"channel": "Campaign",
		"purpose": "Attribution",
		"disposition": "Touched",
		"is_direct_touchpoint": False,
		"evidence_kind": "campaign_touchpoint",
	},
}

# The legacy `outcome` Select field on CRM Interaction conflates true
# Disposition values (Captured/No Response/...) with business-outcome-shaped
# language (Resolved/Converted). `is_business_outcome_like` flags the latter
# so a consumer can tell CRM Student Outcome (the real business result) apart
# from this field without a schema rename -- see the Interaction Disposition
# vs Student Outcome invariant.
OUTCOME_FIELD_MAPPING = {
	"Captured": {"disposition": "Captured", "is_business_outcome_like": False},
	"Follow Up Needed": {"disposition": "Follow Up Needed", "is_business_outcome_like": False},
	"Resolved": {"disposition": "Resolved", "is_business_outcome_like": True},
	"Converted": {"disposition": "Converted", "is_business_outcome_like": True},
	"No Response": {"disposition": "No Response", "is_business_outcome_like": False},
	"Data Error": {"disposition": "Data Error", "is_business_outcome_like": False},
	"Uncontactable": {"disposition": "Uncontactable", "is_business_outcome_like": False},
}

# crm/fcrm/interaction_log.py's create_interaction_from_*() dispatchers
# write these CRM Interaction Type codes. Completeness
# tests assert every one of them has a mapping entry above.
KNOWN_WRITER_INTERACTION_TYPES = frozenset(
	{
		"OUTREACH",
		"MESSAGE_CHATWOOT",
		"CONNECTED",
		"COUNSELING",
		"STAGE_CHANGED",
		"LEAD_ASSIGNED",
		"LEAD_REASSIGNED",
		"OPT_OUT",
		"OPT_IN",
		"BOUNCE",
		"DATA_ERROR",
		"REGISTERED",
		"CHECKED_IN",
		"NO_SHOW",
		"FEEDBACK",
		"CAMPAIGN_TOUCHED",
	}
)

# Direct touchpoints only -- non-negotiable decision #1. Everything else is
# independent evidence carried on a CRM Interaction row for historical/
# migration reasons, not a meaningful admissions touchpoint.
DIRECT_TOUCHPOINT_TYPES = frozenset(
	{name for name, mapping in INTERACTION_TYPE_MAPPING.items() if mapping["is_direct_touchpoint"]}
)


def _canonical_json(mapping):
	return json.dumps(mapping, sort_keys=True, separators=(",", ":"))


# Frozen expected value of CONTENT_HASH below -- both repos assert their own
# computed hash equals this literal, so an unmirrored edit to either copy
# fails that repo's own contract test without a cross-repo import.
FROZEN_CONTENT_HASH = "14ebca6127068138342a296f8034c22534482210c2ca0cdde41bdf8c9a0a1407"

CONTENT_HASH = hashlib.sha256(
	_canonical_json(
		{
			"contract_version": CONTRACT_VERSION,
			"interaction_intelligence_policy": INTERACTION_INTELLIGENCE_POLICY,
			"interaction_type_mapping": INTERACTION_TYPE_MAPPING,
			"outcome_field_mapping": OUTCOME_FIELD_MAPPING,
		}
	).encode()
).hexdigest()


def resolve_interaction_type(interaction_type):
	"""Return the canonical {channel, purpose, disposition, is_direct_touchpoint,
	evidence_kind} mapping for a legacy `interaction_type`, or None if unmapped.

	None means the value predates this contract or is an admin-defined `CRM
	Interaction Type` outside the known writer set -- callers must treat that
	as "unknown evidence kind", never assume it is a direct touchpoint.
	"""
	entry = INTERACTION_TYPE_MAPPING.get(interaction_type)
	return dict(entry) if entry else None


def resolve_outcome(outcome):
	if not outcome:
		return None
	entry = OUTCOME_FIELD_MAPPING.get(outcome)
	return dict(entry) if entry else None


def is_business_outcome_like(outcome):
	resolved = resolve_outcome(outcome)
	return bool(resolved and resolved["is_business_outcome_like"])


class InteractionContractError(ValueError):
	"""A producer or consumer sent an unsupported interaction contract shape."""


def canonical_digest(value):
	"""Return the stable digest used to bind immutable evidence and results."""
	return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _require(mapping, fields, where):
	missing = [field for field in fields if field not in mapping]
	if missing:
		raise InteractionContractError(f"{where} missing required fields: {', '.join(missing)}")


def _reject_unknown_fields(mapping, allowed, where):
	unknown = set(mapping) - allowed
	if unknown:
		raise InteractionContractError(f"{where} has unsupported fields: {', '.join(sorted(unknown))}")


def _is_digest(value):
	return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _require_non_empty_strings(mapping, fields, where):
	for field in fields:
		if not isinstance(mapping[field], str) or not mapping[field].strip():
			raise InteractionContractError(f"{where}.{field} must be a non-empty string")


def _require_positive_int(value, field):
	if not isinstance(value, int) or isinstance(value, bool) or value < 1:
		raise InteractionContractError(f"{field} must be a positive integer")


def _reject_raw_content(value):
	"""Keep transcripts and other raw evidence out of contract envelopes."""
	prohibited = {"content", "raw_content", "transcript", "quoted_text"}
	if isinstance(value, Mapping):
		if prohibited.intersection(value):
			raise InteractionContractError("raw evidence content is not allowed in this envelope")
		for child in value.values():
			_reject_raw_content(child)
	elif isinstance(value, (list, tuple)):
		for child in value:
			_reject_raw_content(child)


def _require_contract_version(payload):
	if payload.get("contract_version") != INTERACTION_INTELLIGENCE_CONTRACT_VERSION:
		raise InteractionContractError("unsupported interaction intelligence contract version")


def validate_interaction_intake(payload):
	"""Validate the minimal Frappe-owned evidence reference sent for analysis."""
	if not isinstance(payload, Mapping):
		raise InteractionContractError("interaction intake must be an object")
	_require_contract_version(payload)
	_reject_raw_content(payload)
	_reject_unknown_fields(
		payload,
		{
			"contract_version", "event_ledger_id", "source", "evidence_ref", "evidence_digest", "sequence",
			"target", "actor", "correlation_id", "idempotency_key", "occurred_at",
		},
		"interaction intake",
	)
	_require(
		payload,
		(
			"event_ledger_id", "source", "evidence_ref", "evidence_digest", "sequence", "target",
			"actor", "correlation_id", "idempotency_key", "occurred_at",
		),
		"interaction intake",
	)
	if not _is_digest(payload["evidence_digest"]):
		raise InteractionContractError("evidence_digest must be a lowercase SHA-256 digest")
	_require_non_empty_strings(payload, ("event_ledger_id", "correlation_id", "idempotency_key", "occurred_at"), "interaction intake")
	_require_positive_int(payload["sequence"], "sequence")
	source = payload["source"]
	evidence_ref = payload["evidence_ref"]
	target = payload["target"]
	actor = payload["actor"]
	if not all(isinstance(item, Mapping) for item in (source, evidence_ref, target, actor)):
		raise InteractionContractError("source, evidence_ref, target, and actor must be objects")
	_require(source, ("provider", "channel", "event_id", "revision", "kind", "state"), "source")
	_require(evidence_ref, ("doctype", "name"), "evidence_ref")
	_require(target, ("doctype", "name"), "target")
	_require(actor, ("id", "role"), "actor")
	_reject_unknown_fields(source, {"provider", "channel", "event_id", "revision", "kind", "state"}, "source")
	_reject_unknown_fields(evidence_ref, {"doctype", "name"}, "evidence_ref")
	_reject_unknown_fields(target, {"doctype", "name"}, "target")
	_reject_unknown_fields(actor, {"id", "role"}, "actor")
	_require_non_empty_strings(source, ("provider", "channel", "event_id", "kind", "state"), "source")
	_require_non_empty_strings(evidence_ref, ("doctype", "name"), "evidence_ref")
	_require_non_empty_strings(target, ("doctype", "name"), "target")
	_require_non_empty_strings(actor, ("id", "role"), "actor")
	if source["kind"] not in {"message", "call"}:
		raise InteractionContractError("source.kind must be message or call")
	if source["state"] not in {"draft", "final", "correction"}:
		raise InteractionContractError("source.state must be draft, final, or correction")
	_require_positive_int(source["revision"], "source.revision")
	if source["state"] == "draft":
		raise InteractionContractError("draft call evidence must not enter analysis")
	if actor["role"] not in {"student", "advisor", "system"}:
		raise InteractionContractError("actor.role is unsupported")


def validate_analysis_result(payload):
	"""Validate a bounded result that can reference, but never copy, evidence."""
	if not isinstance(payload, Mapping):
		raise InteractionContractError("analysis result must be an object")
	_require_contract_version(payload)
	_reject_raw_content(payload)
	_reject_unknown_fields(
		payload,
		{
			"contract_version", "analysis_run_id", "episode_id", "source_revision", "source_digest", "state",
			"model_revision", "policy_revision", "intent",
		},
		"analysis result",
	)
	_require(
		payload,
		(
			"analysis_run_id", "episode_id", "source_revision", "source_digest", "state",
			"model_revision", "policy_revision",
		),
		"analysis result",
	)
	if payload["state"] not in SUPPORTED_ANALYSIS_RESULT_STATES:
		raise InteractionContractError("unsupported analysis result state")
	if not _is_digest(payload["source_digest"]):
		raise InteractionContractError("source_digest must be a lowercase SHA-256 digest")
	_require_non_empty_strings(
		payload,
		("analysis_run_id", "episode_id", "model_revision", "policy_revision"),
		"analysis result",
	)
	_require_positive_int(payload["source_revision"], "source_revision")
	intent = payload.get("intent")
	if payload["state"] == "intent_bearing":
		if not isinstance(intent, Mapping):
			raise InteractionContractError("intent_bearing results require an intent reference")
		_require(intent, ("semantic_key", "evidence_refs"), "intent")
		_reject_unknown_fields(intent, {"semantic_key", "evidence_refs"}, "intent")
		_require_non_empty_strings(intent, ("semantic_key",), "intent")
		evidence_refs = intent["evidence_refs"]
		if not isinstance(evidence_refs, (list, tuple)) or not evidence_refs:
			raise InteractionContractError("intent requires at least one evidence reference")
		for ref in evidence_refs:
			if not isinstance(ref, Mapping):
				raise InteractionContractError("intent evidence references must be objects")
			_reject_unknown_fields(ref, {"doctype", "name", "actor_role"}, "intent evidence reference")
			_require(ref, ("doctype", "name", "actor_role"), "intent evidence reference")
			_require_non_empty_strings(ref, ("doctype", "name", "actor_role"), "intent evidence reference")
			if ref["actor_role"] != "student":
				raise InteractionContractError("only student evidence can substantiate an intent")
	elif intent is not None:
		raise InteractionContractError("only intent_bearing results may carry an intent")
