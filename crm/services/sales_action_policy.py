"""Single Frappe-owned policy registry for v2 controlled actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import frappe
from frappe.utils import now_datetime

V2_ACTION_TYPES = (
	"CALL",
	"EMAIL",
	"MESSAGE",
	"COUNSELING",
	"MEETING",
	"EVENT_INVITE",
	"CAMPUS_VISIT",
	"DOCUMENT_REQUEST",
	"APPLICATION_SUPPORT",
	"PARENT_CONTACT",
	"HANDOFF",
)


@dataclass(frozen=True)
class ActionPolicy:
	action_type: str
	required_inputs: tuple[str, ...]
	actors: tuple[str, ...]
	can_dispatch: bool = True
	completion_evidence: tuple[str, ...] = ("completed_at",)
	outcomes: tuple[str, ...] = (
		"NO_RESPONSE",
		"INTEREST_INCREASED",
		"NEEDS_MORE_INFORMATION",
		"NOT_INTERESTED",
	)


ACTION_POLICIES = {
	action: ActionPolicy(action, required_inputs, actors, can_dispatch=action not in {"HANDOFF"})
	for action, required_inputs, actors in (
		("CALL", ("objective", "package"), ("Sale", "Lead Sales")),
		("EMAIL", ("objective", "package"), ("Sale", "Lead Sales")),
		("MESSAGE", ("objective", "channel"), ("Sale", "Lead Sales")),
		("COUNSELING", ("objective",), ("Sale", "Lead Sales")),
		("MEETING", ("objective", "scheduled_at"), ("Sale", "Lead Sales")),
		("EVENT_INVITE", ("objective", "event"), ("Sale", "Lead Sales")),
		("CAMPUS_VISIT", ("objective", "campus"), ("Sale", "Lead Sales")),
		("DOCUMENT_REQUEST", ("objective", "document_type"), ("Sale", "Lead Sales")),
		("APPLICATION_SUPPORT", ("objective", "application_step"), ("Sale", "Lead Sales")),
		("PARENT_CONTACT", ("objective", "authority", "channel", "timing"), ("Sale", "Lead Sales")),
		("HANDOFF", ("objective", "handoff_to"), ("Sale", "Lead Sales")),
	)
}


def policy_for(action_type: str) -> ActionPolicy:
	try:
		return ACTION_POLICIES[action_type]
	except KeyError as exc:
		raise ValueError(f"Unsupported v2 action type: {action_type}") from exc


def _parent_authority_is_valid(student: str, channel: str | None = None, at: datetime | None = None) -> bool:
	at = at or now_datetime()
	filters = {
		"student": student,
		"relationship_verified": 1,
		"revoked_at": ["is", "not set"],
		"effective_at": ["<=", at],
	}
	authorities = frappe.get_all(
		"CRM Parent Contact Authority",
		filters=filters,
		fields=["name", "allowed_channels", "expires_at", "lawful_basis"],
		limit_page_length=50,
	)
	for authority in authorities:
		if authority.expires_at and authority.expires_at < at:
			continue
		if not authority.lawful_basis:
			continue
		raw_channels = authority.allowed_channels or []
		channels = frappe.parse_json(raw_channels) if isinstance(raw_channels, str) else raw_channels
		if not isinstance(channels, (list, tuple)) or not channels:
			continue
		if channel:
			if channel not in channels:
				continue
		return True
	return False


def validate_action_command(
	action_type: str, *, student: str, inputs: dict, actor_roles: set[str], at=None
) -> ActionPolicy:
	policy = policy_for(action_type)
	missing = [field for field in policy.required_inputs if not inputs.get(field)]
	if missing:
		raise ValueError(f"Missing required action inputs: {', '.join(missing)}")
	if not actor_roles.intersection(policy.actors) and "System Manager" not in actor_roles:
		raise frappe.PermissionError("Actor is not permitted for this action")
	if action_type == "PARENT_CONTACT" and not _parent_authority_is_valid(student, inputs.get("channel"), at):
		raise frappe.PermissionError(
			"Parent Contact Authority is missing, expired, revoked, or channel-limited"
		)
	return policy


def allowed_generation_actions(student: str) -> list[str]:
	"""Return Frappe policy-available actions, without SLA/timing inference."""
	actions = list(V2_ACTION_TYPES)
	if not _parent_authority_is_valid(student):
		actions.remove("PARENT_CONTACT")
	return actions
