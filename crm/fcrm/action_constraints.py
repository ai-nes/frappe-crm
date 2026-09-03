"""Shared validation and defaults for the canonical CRM Action catalog.

This module is deliberately independent from Frappe so seed data and unit
tests use the same contract as the DocType controller.
"""

from __future__ import annotations

import json
from typing import Any

from crm.fcrm.action_type_catalog import ACTION_TYPE_METADATA
from crm.fcrm.nba_timing import TIME_SLOTS

CHANNELS = frozenset({"NONE", "CALL", "EMAIL", "MESSAGE"})
ACTOR_ROLES = frozenset(
	{"Sale", "Lead Sales", "Marketing", "Promoter", "Admissions Director", "System Manager"}
)
EXECUTION_TYPES = frozenset({"MANUAL", "AI_ASSISTED"})

# These actions have an unambiguous provider channel from their code. Other
# actions keep a configurable default because their content can be delivered
# through more than one channel.
FIXED_CHANNELS = {
	"CALL": "CALL",
	"VIDEO_CALL": "CALL",
	"CALL_BACK": "CALL",
	"SEND_ZALO": "MESSAGE",
	"SEND_SMS": "MESSAGE",
	"SEND_EMAIL": "EMAIL",
}

MANAGER_ONLY_ACTIONS = frozenset(
	{
		"REASSIGN_ADVISOR",
		"ESCALATE_SUPERVISOR",
		"ESCALATE_HIGH_INTENT",
		"ESCALATE_TO_SENIOR",
		"ESCALATE_CASE",
		"REQUEST_SUPERVISOR_REVIEW",
	}
)

APPROVAL_ACTIONS = frozenset(
	{
		"SEND_OFFER",
		"MARK_LOST",
		"ACTIVATE_WINBACK",
		"ESCALATE_SUPERVISOR",
		"ESCALATE_HIGH_INTENT",
		"ESCALATE_TO_SENIOR",
		"ESCALATE_CASE",
		"REQUEST_SUPERVISOR_REVIEW",
	}
)


def _actors_for(code: str) -> list[str]:
	if code in MANAGER_ONLY_ACTIONS:
		return ["Lead Sales", "Admissions Director"]
	return ["Sale", "Lead Sales", "Admissions Director"]


def _checked(value: Any) -> bool:
	return value in (1, "1", True)


def defaults_for_action(code: str, category: str) -> dict[str, Any]:
	"""Return safe, deterministic master-data defaults for one action code."""
	if code not in ACTION_TYPE_METADATA:
		raise ValueError(f"Unsupported CRM Action code: {code}")
	if ACTION_TYPE_METADATA[code]["category"] != category:
		raise ValueError(f"CRM Action {code} does not belong to Action Type {category}.")
	ai_allowed = category != "INTERNAL"
	return {
		"default_channel": FIXED_CHANNELS.get(code, "NONE"),
		"allowed_actors": json.dumps(_actors_for(code), ensure_ascii=False),
		"requires_approval": int(code in APPROVAL_ACTIONS),
		"auto_execute": 0,
		"execution_type": "AI_ASSISTED" if ai_allowed else "MANUAL",
		"ai_allowed": int(ai_allowed),
	}


def _normalise_actors(value: Any) -> list[str]:
	if isinstance(value, str):
		try:
			value = json.loads(value) if value else []
		except (TypeError, ValueError) as exc:
			raise ValueError("allowed_actors must be a JSON array.") from exc
	if not isinstance(value, list) or not value or any(not isinstance(actor, str) for actor in value):
		raise ValueError("allowed_actors must be a non-empty JSON array of CRM roles.")
	if len(value) != len(set(value)):
		raise ValueError("allowed_actors cannot contain duplicate roles.")
	if any(actor not in ACTOR_ROLES for actor in value):
		raise ValueError("allowed_actors contains an unsupported CRM role.")
	return value


def _normalise_time_slots(value: Any) -> list[str]:
	if value in (None, ""):
		return []
	if isinstance(value, str):
		try:
			value = json.loads(value) if value else []
		except (TypeError, ValueError) as exc:
			raise ValueError("allowed_time_slots must be a JSON array.") from exc
	if not isinstance(value, list) or any(not isinstance(slot, str) for slot in value):
		raise ValueError("allowed_time_slots must be a JSON array of time slot codes.")
	if len(value) != len(set(value)):
		raise ValueError("allowed_time_slots cannot contain duplicate slots.")
	if any(slot not in TIME_SLOTS for slot in value):
		raise ValueError(f"allowed_time_slots must only contain {list(TIME_SLOTS)}.")
	return value


def validate_action_config(
	code: str,
	category: str,
	default_channel: str,
	allowed_actors: Any,
	requires_approval: Any,
	auto_execute: Any,
	enabled: Any,
	execution_type: str = "MANUAL",
	ai_allowed: Any = False,
	allowed_time_slots: Any = None,
) -> list[str]:
	"""Validate the mutable configuration of a CRM Action master row.

	Returns the normalized actor list so callers can reuse the parsed value.
	"""
	_normalise_time_slots(allowed_time_slots)
	metadata = ACTION_TYPE_METADATA.get(code)
	if not metadata:
		raise ValueError("CRM Action code must be one of the canonical 79 codes.")
	if metadata["category"] != category:
		raise ValueError(f"CRM Action {code} must use Action Type {metadata['category']}.")
	if default_channel not in CHANNELS:
		raise ValueError("CRM Action default channel is unsupported.")
	fixed_channel = FIXED_CHANNELS.get(code)
	if fixed_channel and default_channel not in {fixed_channel, "NONE"}:
		raise ValueError(f"CRM Action {code} must use channel {fixed_channel} or NONE.")
	actors = _normalise_actors(allowed_actors)
	if code in MANAGER_ONLY_ACTIONS and any(
		actor not in {"Lead Sales", "Admissions Director", "System Manager"} for actor in actors
	):
		raise ValueError(f"CRM Action {code} is restricted to manager roles.")
	if execution_type not in EXECUTION_TYPES:
		raise ValueError("CRM Action execution type is unsupported.")
	if _checked(requires_approval) and _checked(auto_execute):
		raise ValueError("A CRM Action cannot require approval and auto-execute at the same time.")
	if _checked(auto_execute) and not _checked(enabled):
		raise ValueError("A disabled CRM Action cannot auto-execute.")
	if execution_type == "AI_ASSISTED" and not _checked(ai_allowed):
		raise ValueError("AI-assisted CRM Actions must allow AI execution.")
	return actors
