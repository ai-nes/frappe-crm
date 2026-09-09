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

from crm.fcrm.nba_context import validate_decision_signals

CONTRACT_VERSION = 4

INTERACTION_INTELLIGENCE_CONTRACT_VERSION = "interaction-intelligence-v1"
INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION = "interaction-analysis-v2"
DECISION_SIGNALS_SCHEMA_REVISION = "nba-decision-signals-v1"
SILENCE_WINDOW_SECONDS = 15 * 60
SUPPORTED_ANALYSIS_RESULT_STATES = frozenset({"no_intent", "intent_bearing", "unknown", "failed"})

# Additive `intelligence` settlement block -- mirrors crm-agents'
# app/contracts/interaction_semantics.py. Sits at the settlement payload top
# level (sibling of `intent`), never inside the digest-bound envelope, so a
# `no_intent` result can carry a summary and omitting the block reproduces the
# exact legacy digest.
INTELLIGENCE_SUMMARY_MAX_CHARS = 600
INTELLIGENCE_SENTIMENTS = frozenset({"positive", "neutral", "negative", "mixed"})
INTELLIGENCE_READINESS = frozenset({"ready", "hesitant", "unknown"})
INTELLIGENCE_MAX_CONCERNS = 8
INTELLIGENCE_STATES = frozenset({"intent_bearing", "no_intent"})
_INTELLIGENCE_CONCERN_MAX_CHARS = 64
_INTELLIGENCE_FIELDS = frozenset({"summary", "sentiment", "entities", "readiness", "concerns"})
_INTELLIGENCE_MAX_ENTITY_TYPES = 12
_INTELLIGENCE_MAX_ENTITY_VALUES = 12
_INTELLIGENCE_ENTITY_STR_MAX_CHARS = 120
_INTELLIGENCE_RESERVED_ENTITY_KEYS = frozenset({"content", "raw_content", "transcript", "quoted_text"})

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
	"intelligence": {
		"placement": "settlement_payload_top_level_sibling_of_intent",
		"digest_bound": False,
		"states": ("intent_bearing", "no_intent"),
		"fields": ("summary", "sentiment", "entities", "readiness", "concerns"),
		"summary": "bounded_single_line_quote_free_model_prose",
		"summary_max_chars": INTELLIGENCE_SUMMARY_MAX_CHARS,
		"sentiment_values": tuple(sorted(INTELLIGENCE_SENTIMENTS)),
		"readiness_values": tuple(sorted(INTELLIGENCE_READINESS)),
		"max_concerns": INTELLIGENCE_MAX_CONCERNS,
		"entities": "bounded_sanitized_string_map_reserved_keys_rejected",
		"max_entity_types": _INTELLIGENCE_MAX_ENTITY_TYPES,
		"max_entity_values": _INTELLIGENCE_MAX_ENTITY_VALUES,
		"omitted_reproduces_legacy_digest": True,
	},
	"term": {
		"semantic_key": "immutable",
		"label": "mutable_display_only",
		"retirement": "retire_without_rewriting_history",
		"enforcement": "phase_two_frappe_schema_migration",
	},
	"compatibility": {
		"supported_versions": (INTERACTION_INTELLIGENCE_CONTRACT_VERSION,),
		"analysis_result_versions": (
			INTERACTION_INTELLIGENCE_CONTRACT_VERSION,
			INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION,
		),
		"decision_signals_schema_revision": DECISION_SIGNALS_SCHEMA_REVISION,
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
	"PHONE_CALL": {"channel": "Call", "purpose": "Conversation", "disposition": "Occurred", "is_direct_touchpoint": True, "evidence_kind": "interaction"},
	"MESSAGE": {"channel": "Chat", "purpose": "Conversation", "disposition": "Received", "is_direct_touchpoint": True, "evidence_kind": "interaction"},
	"EMAIL": {"channel": "Email", "purpose": "Conversation", "disposition": "Sent", "is_direct_touchpoint": True, "evidence_kind": "interaction"},
	"MEETING": {"channel": "Meeting", "purpose": "Counseling", "disposition": "Occurred", "is_direct_touchpoint": True, "evidence_kind": "interaction"},
	"FORM_SUBMISSION": {"channel": "Form", "purpose": "Application", "disposition": "Submitted", "is_direct_touchpoint": False, "evidence_kind": "application_event"},
	"APPLICATION_UPDATE": {"channel": "System", "purpose": "Application", "disposition": "Updated", "is_direct_touchpoint": False, "evidence_kind": "application_event"},
	"DOCUMENT_SUBMISSION": {"channel": "Document", "purpose": "Application", "disposition": "Submitted", "is_direct_touchpoint": False, "evidence_kind": "document_event"},
	"EVENT_PARTICIPATION": {"channel": "Event", "purpose": "Event Engagement", "disposition": "Participated", "is_direct_touchpoint": False, "evidence_kind": "event_participation"},
	"PAYMENT": {"channel": "Payment", "purpose": "Enrollment", "disposition": "Paid", "is_direct_touchpoint": False, "evidence_kind": "payment_event"},
	"SYSTEM_ACTIVITY": {"channel": "System", "purpose": "Lifecycle", "disposition": "Recorded", "is_direct_touchpoint": False, "evidence_kind": "system_event"},
	"NOTE": {"channel": "Internal", "purpose": "Counseling", "disposition": "Noted", "is_direct_touchpoint": False, "evidence_kind": "sales_note"},
	"OTHER": {"channel": "Unknown", "purpose": "Other", "disposition": "Occurred", "is_direct_touchpoint": False, "evidence_kind": "interaction"},
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
		"PHONE_CALL",
		"MESSAGE",
		"EMAIL",
		"MEETING",
		"EVENT_PARTICIPATION",
		"SYSTEM_ACTIVITY",
		"NOTE",
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
FROZEN_CONTENT_HASH = "ee6a9db7833f623c34e64db0ad657d657256eb2d76736dc3dab40e1cac9c9855"

CONTENT_HASH = hashlib.sha256(
	_canonical_json(
		{
			"contract_version": CONTRACT_VERSION,
			"analysis_result_contract_version": INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION,
			"decision_signals_schema_revision": DECISION_SIGNALS_SCHEMA_REVISION,
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


def _validate_intelligence(block, *, state):
	"""Validate the additive `intelligence` settlement block (mirror)."""
	if state not in INTELLIGENCE_STATES:
		raise InteractionContractError(
			"intelligence is only valid on intent_bearing or no_intent results"
		)
	if not isinstance(block, Mapping):
		raise InteractionContractError("intelligence must be an object")
	_reject_unknown_fields(block, set(_INTELLIGENCE_FIELDS), "intelligence")
	summary = block.get("summary", "")
	if not isinstance(summary, str):
		raise InteractionContractError("intelligence.summary must be a string")
	if len(summary) > INTELLIGENCE_SUMMARY_MAX_CHARS:
		raise InteractionContractError("intelligence.summary exceeds its length bound")
	if "\n" in summary or "\r" in summary:
		raise InteractionContractError("intelligence.summary must be a single line")
	if "sentiment" in block and block["sentiment"] not in INTELLIGENCE_SENTIMENTS:
		raise InteractionContractError("intelligence.sentiment is unsupported")
	if "readiness" in block and block["readiness"] not in INTELLIGENCE_READINESS:
		raise InteractionContractError("intelligence.readiness is unsupported")
	entities = block.get("entities", {})
	if not isinstance(entities, Mapping) or len(entities) > _INTELLIGENCE_MAX_ENTITY_TYPES:
		raise InteractionContractError("intelligence.entities must be a bounded string map")
	for key, values in entities.items():
		if (
			not isinstance(key, str)
			or not key
			or key.lower() in _INTELLIGENCE_RESERVED_ENTITY_KEYS
			or not isinstance(values, (list, tuple))
			or len(values) > _INTELLIGENCE_MAX_ENTITY_VALUES
			or not all(
				isinstance(value, str) and 0 < len(value) <= _INTELLIGENCE_ENTITY_STR_MAX_CHARS
				for value in values
			)
		):
			raise InteractionContractError("intelligence.entities must map strings to bounded string lists")
	concerns = block.get("concerns", [])
	if not isinstance(concerns, (list, tuple)) or len(concerns) > INTELLIGENCE_MAX_CONCERNS:
		raise InteractionContractError("intelligence.concerns must be a bounded list")
	if not all(
		isinstance(concern, str) and 0 < len(concern) <= _INTELLIGENCE_CONCERN_MAX_CHARS
		for concern in concerns
	):
		raise InteractionContractError("intelligence.concerns entries must be bounded strings")


# Public name for cross-module callers (settlement handler); keep the private
# alias so the mirror stays byte-comparable with the crm-agents contract.
validate_intelligence = _validate_intelligence


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
	if payload.get("contract_version") not in {
		INTERACTION_INTELLIGENCE_CONTRACT_VERSION,
		INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION,
	}:
		raise InteractionContractError("unsupported interaction intelligence contract version")
	_reject_raw_content(payload)
	_reject_unknown_fields(
		payload,
		{
			"contract_version", "analysis_run_id", "episode_id", "source_revision", "source_digest", "state",
			"model_revision", "policy_revision", "intent", "decision_signals", "intelligence",
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
	if payload.get("intelligence") is not None:
		_validate_intelligence(payload["intelligence"], state=payload["state"])
	decision_signals = payload.get("decision_signals")
	if decision_signals is not None:
		if payload.get("contract_version") != INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION:
			raise InteractionContractError("decision_signals requires interaction-analysis-v2")
		try:
			validate_decision_signals(decision_signals)
		except ValueError as exc:
			raise InteractionContractError("invalid decision_signals") from exc
		if payload["state"] == "failed" and decision_signals.get("observations"):
			raise InteractionContractError("failed results cannot carry decision signals")
	elif payload.get("contract_version") == INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION:
		raise InteractionContractError("interaction-analysis-v2 requires decision_signals")
