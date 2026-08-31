"""Canonical Interaction vocabulary — frozen cross-repo contract.

Byte-identical mapping to crm-agents' `app/contracts/interaction_semantics.py`
(no shared package exists across the two repos). `CONTENT_HASH` freezes the
mapping so an edit to either copy that isn't mirrored to the other fails that
repo's own contract test immediately, without a cross-repo import at test
time. Bump CONTRACT_VERSION (and update CONTENT_HASH in both repos) for any
intentional change, keeping both copies in lockstep.

This module answers Channel / Purpose / Disposition and "is this a direct
admissions touchpoint, or independent evidence?" for the legacy
`CRM Term` (Link, open vocabulary) and `outcome` (Select) fields
on CRM Interaction -- it does not change either field or any writer.
"""

import hashlib
import json

CONTRACT_VERSION = 1

# Non-negotiable: Assignment, consent, campaign attribution, event
# participation, and internal tasks are independent evidence, not
# auto-mirrored interactions. Until the writers in interaction_log.py fully
# canonicalize, these legacy types keep flowing onto CRM Interaction rows at
# the physical layer, so the contract marks them non-direct-touchpoint
# rather than pretending they don't exist there.
INTERACTION_TYPE_MAPPING = {
	"Outreach": {
		"channel": "Email",
		"purpose": "Outreach",
		"disposition": "Sent",
		"is_direct_touchpoint": True,
		"evidence_kind": "interaction",
	},
	"Connected": {
		"channel": "Call",
		"purpose": "Outreach",
		"disposition": "Connected",
		"is_direct_touchpoint": True,
		"evidence_kind": "interaction",
	},
	"Counseling": {
		"channel": "Call",
		"purpose": "Counseling",
		"disposition": "Connected",
		"is_direct_touchpoint": True,
		"evidence_kind": "interaction",
	},
	"Stage Changed": {
		"channel": "System",
		"purpose": "Lifecycle",
		"disposition": "Stage Changed",
		"is_direct_touchpoint": False,
		"evidence_kind": "lifecycle_event",
	},
	"Lead Assigned": {
		"channel": "System",
		"purpose": "Lifecycle",
		"disposition": "Assigned",
		"is_direct_touchpoint": False,
		"evidence_kind": "ownership_event",
	},
	"Lead Reassigned": {
		"channel": "System",
		"purpose": "Lifecycle",
		"disposition": "Reassigned",
		"is_direct_touchpoint": False,
		"evidence_kind": "ownership_event",
	},
	"Opt-out": {
		"channel": "System",
		"purpose": "Consent",
		"disposition": "Opted Out",
		"is_direct_touchpoint": False,
		"evidence_kind": "consent_event",
	},
	"Opt-in": {
		"channel": "System",
		"purpose": "Consent",
		"disposition": "Opted In",
		"is_direct_touchpoint": False,
		"evidence_kind": "consent_event",
	},
	"Bounce": {
		"channel": "System",
		"purpose": "Consent",
		"disposition": "Bounced",
		"is_direct_touchpoint": False,
		"evidence_kind": "consent_event",
	},
	"Data Error": {
		"channel": "System",
		"purpose": "Consent",
		"disposition": "Suppressed",
		"is_direct_touchpoint": False,
		"evidence_kind": "consent_event",
	},
	"Registered": {
		"channel": "Event",
		"purpose": "Event Engagement",
		"disposition": "Registered",
		"is_direct_touchpoint": False,
		"evidence_kind": "event_participation",
	},
	"Checked-in": {
		"channel": "Event",
		"purpose": "Event Engagement",
		"disposition": "Checked-in",
		"is_direct_touchpoint": False,
		"evidence_kind": "event_participation",
	},
	"No-show": {
		"channel": "Event",
		"purpose": "Event Engagement",
		"disposition": "No-show",
		"is_direct_touchpoint": False,
		"evidence_kind": "event_participation",
	},
	"Feedback": {
		"channel": "Event",
		"purpose": "Event Engagement",
		"disposition": "Feedback Given",
		"is_direct_touchpoint": False,
		"evidence_kind": "event_participation",
	},
	"Campaign Touched": {
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
# currently write these legacy CRM Term values. Completeness
# tests assert every one of them has a mapping entry above.
KNOWN_WRITER_INTERACTION_TYPES = frozenset(
	{
		"Outreach",
		"Connected",
		"Counseling",
		"Stage Changed",
		"Lead Assigned",
		"Lead Reassigned",
		"Opt-out",
		"Opt-in",
		"Bounce",
		"Data Error",
		"Registered",
		"Checked-in",
		"No-show",
		"Feedback",
		"Campaign Touched",
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
FROZEN_CONTENT_HASH = "bb828d77092d57d43e008ca6b2903e4293903007d353ea910afe30785a359479"

CONTENT_HASH = hashlib.sha256(
	_canonical_json(
		{
			"contract_version": CONTRACT_VERSION,
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
