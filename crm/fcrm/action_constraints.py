"""Shared validation and defaults for built-in and custom CRM Actions.

This module is deliberately independent from Frappe so seed data and unit
tests use the same contract as the DocType controller.
"""

from __future__ import annotations

import json
from typing import Any

from crm.fcrm.action_type_catalog import ACTION_TYPE_METADATA, is_valid_configuration_code
from crm.fcrm.nba_timing import TIME_SLOTS

CHANNELS = frozenset({"NONE", "CALL", "EMAIL", "MESSAGE"})
TASK_ACCEPTOR_ROLES = ("CTV Sale", "Sale", "Lead Sale")
DEFAULT_ACTION_ACTORS = (*TASK_ACCEPTOR_ROLES, "Admissions Director")
ACTOR_ROLES = frozenset(
	{*DEFAULT_ACTION_ACTORS, "Marketing", "Promoter", "System Manager"}
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

# Recipient-facing actions whose delivery channel is unambiguous from the
# action's intent even though the code does not name a channel (unlike
# FIXED_CHANNELS). Anything absent from both maps stays NONE -- an
# internal-state, routing, or escalation action with no student/parent
# recipient. An operator can still override any of these per row.
DEFAULT_CHANNELS = {
	# Advisor-led conversations
	"ADVISE_MAJOR": "CALL",
	"ADVISE_TUITION": "CALL",
	"ADVISE_SCHOLARSHIP": "CALL",
	"ADVISE_CAREER": "CALL",
	"ADVISE_PARENT": "CALL",
	"COMPARE_MAJORS": "CALL",
	"COMPARE_CAMPUSES": "CALL",
	"BOOK_1ON1_CONSULTATION": "CALL",
	"BOOK_PARENT_CONSULTATION": "CALL",
	"CONTACT_PARENT": "CALL",
	"CHECK_APPLICATION": "CALL",
	"CONFIRM_APPLICATION_RECEIVED": "CALL",
	"ASSIST_APPLICATION_FEE": "CALL",
	"REQUEST_MISSING_DOCUMENT": "CALL",
	"GUIDE_NEXT_STEP": "CALL",
	"FOLLOW_UP_SILENT_LEAD": "CALL",
	"REENGAGE_LEAD": "CALL",
	"ASK_DECISION_REASON": "CALL",
	"SCHEDULE_LATER_FOLLOWUP": "CALL",
	# Content and event invitations
	"SEND_MAJOR_INFO": "EMAIL",
	"SEND_PROGRAM_INFO": "EMAIL",
	"SEND_TUITION_INFO": "EMAIL",
	"SEND_SCHOLARSHIP_INFO": "EMAIL",
	"SEND_PROMOTION_INFO": "EMAIL",
	"SEND_ADMISSION_INFO": "EMAIL",
	"SEND_DORM_INFO": "EMAIL",
	"SEND_CAREER_INFO": "EMAIL",
	"SEND_BROCHURE": "EMAIL",
	"SEND_MAJOR_VIDEO": "EMAIL",
	"SEND_RELEVANT_FAQ": "EMAIL",
	"SEND_PERSONALIZED_CONTENT": "EMAIL",
	"SEND_TESTIMONIAL": "EMAIL",
	"SEND_APPLICATION_CHECKLIST": "EMAIL",
	"SEND_OFFER": "EMAIL",
	"SEND_OBJECTION_CONTENT": "EMAIL",
	"SEND_PARENT_TUITION": "EMAIL",
	"SEND_PARENT_SCHOLARSHIP": "EMAIL",
	"SEND_PARENT_CAREER_INFO": "EMAIL",
	"SEND_TRAINING_ROADMAP": "EMAIL",
	"SEND_FINANCIAL_PLAN": "EMAIL",
	"INVITE_OPEN_DAY": "EMAIL",
	"INVITE_CAMPUS_TOUR": "EMAIL",
	"INVITE_CAMPUS_VISIT": "EMAIL",
	"INVITE_WEBINAR": "EMAIL",
	"INVITE_WORKSHOP": "EMAIL",
	"INVITE_CLASS_EXPERIENCE": "EMAIL",
	"INVITE_STEM_EVENT": "EMAIL",
	"INVITE_MOCK_TEST": "EMAIL",
	"INVITE_PARENT_EVENT": "EMAIL",
	# Short reminders
	"REMIND_APPLICATION": "MESSAGE",
	"REMIND_COMPLETE_APPLICATION": "MESSAGE",
	"REMIND_APPLICATION_DEADLINE": "MESSAGE",
	"REMIND_ENROLLMENT_DEADLINE": "MESSAGE",
}

# Daily windows any recipient-facing action may run in: morning through
# evening, never overnight (the "0-6" slot). A NONE-channel action carries no
# window restriction.
CONTACT_TIME_SLOTS: tuple[str, ...] = ("6-12", "12-18", "18-24")

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
		return ["Lead Sale", "Admissions Director"]
	return list(DEFAULT_ACTION_ACTORS)


def _checked(value: Any) -> bool:
	return value in (1, "1", True)


def defaults_for_action(code: str, category: str) -> dict[str, Any]:
	"""Return safe, deterministic master-data defaults for one action code."""
	if code not in ACTION_TYPE_METADATA:
		raise ValueError(f"Unsupported CRM Action code: {code}")
	if ACTION_TYPE_METADATA[code]["category"] != category:
		raise ValueError(f"CRM Action {code} does not belong to Action Type {category}.")
	ai_allowed = category != "INTERNAL"
	channel = FIXED_CHANNELS.get(code) or DEFAULT_CHANNELS.get(code, "NONE")
	return {
		"default_channel": channel,
		"allowed_time_slots": json.dumps(
			list(CONTACT_TIME_SLOTS) if channel != "NONE" else [], ensure_ascii=False
		),
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
	allow_custom: bool = False,
) -> list[str]:
	"""Validate the mutable configuration of a CRM Action master row.

	Returns the normalized actor list so callers can reuse the parsed value.
	"""
	_normalise_time_slots(allowed_time_slots)
	if not is_valid_configuration_code(code):
		raise ValueError("CRM Action code must contain only uppercase letters, numbers, and underscores.")
	metadata = ACTION_TYPE_METADATA.get(code)
	if not metadata and not allow_custom:
		raise ValueError("CRM Action code must be one of the canonical 79 codes.")
	if metadata and metadata["category"] != category:
		raise ValueError(f"CRM Action {code} must use Action Type {metadata['category']}.")
	if default_channel not in CHANNELS:
		raise ValueError("CRM Action default channel is unsupported.")
	fixed_channel = FIXED_CHANNELS.get(code)
	if fixed_channel and default_channel not in {fixed_channel, "NONE"}:
		raise ValueError(f"CRM Action {code} must use channel {fixed_channel} or NONE.")
	actors = _normalise_actors(allowed_actors)
	if code in MANAGER_ONLY_ACTIONS and any(
		actor not in {"Lead Sale", "Admissions Director", "System Manager"} for actor in actors
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
