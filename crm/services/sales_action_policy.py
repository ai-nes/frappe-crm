"""Single Frappe-owned policy registry for v2 controlled actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import frappe
from frappe.utils import now_datetime

from crm.fcrm.action_type_catalog import ACTION_TYPE_CATALOG, action_category
from crm.fcrm.action_type_registry import available_action_types

V2_ACTION_TYPES = tuple(available_action_types())

ACTION_OPERATIONS = ("EDIT", "DISPATCH", "SCHEDULE", "ASSIGN", "RELEASE", "RECORD_OUTCOME")
PARENT_CONTACT_ACTION_TYPES = frozenset({"PARENT_CONTACT", "CONTACT_PARENT"})


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


_DEFAULT_ACTORS = ("Sale", "Lead Sales", "Admissions Director")
_DEFAULT_POLICY = ("objective",)

# Every catalog row is executable as a governed work item. Action-specific
# provider packages can be added later without making the 79-row master
# catalog unusable in decisions or CRUD screens.
ACTION_POLICIES = {
	code: ActionPolicy(code, _DEFAULT_POLICY, _DEFAULT_ACTORS)
	for code, _display_name, _category in ACTION_TYPE_CATALOG
}
ACTION_POLICIES.update(
	{
		"CALL": ActionPolicy("CALL", ("objective", "package"), ("Sale", "Lead Sales")),
		"EMAIL": ActionPolicy("EMAIL", ("objective", "package"), ("Sale", "Lead Sales")),
		"MESSAGE": ActionPolicy("MESSAGE", ("objective", "channel"), ("Sale", "Lead Sales")),
		"COUNSELING": ActionPolicy("COUNSELING", _DEFAULT_POLICY, ("Sale", "Lead Sales")),
		"MEETING": ActionPolicy("MEETING", ("objective", "scheduled_at"), ("Sale", "Lead Sales")),
		"EVENT_INVITE": ActionPolicy("EVENT_INVITE", ("objective", "event"), ("Sale", "Lead Sales")),
		"CAMPUS_VISIT": ActionPolicy("CAMPUS_VISIT", ("objective", "campus"), ("Sale", "Lead Sales")),
		"DOCUMENT_REQUEST": ActionPolicy("DOCUMENT_REQUEST", ("objective", "document_type"), ("Sale", "Lead Sales")),
		"APPLICATION_SUPPORT": ActionPolicy("APPLICATION_SUPPORT", ("objective", "application_step"), ("Sale", "Lead Sales")),
		"PARENT_CONTACT": ActionPolicy("PARENT_CONTACT", ("objective", "authority", "channel", "timing"), ("Sale", "Lead Sales")),
		"HANDOFF": ActionPolicy("HANDOFF", ("objective", "handoff_to"), ("Sale", "Lead Sales"), can_dispatch=False),
	}
)


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


def parent_authority_is_valid(student: str, at: datetime | None = None) -> bool:
	"""Expose the parent-contact check for decision-context projections."""
	return _parent_authority_is_valid(student, at=at)


def require_parent_contact_authority(action_type: str | None, student: str, channel: str | None = None, at=None):
	"""Raise when a parent-contact action lacks current verified authority."""
	if (
		action_type in PARENT_CONTACT_ACTION_TYPES
		or action_category(action_type) == "PARENT"
	) and not _parent_authority_is_valid(student, channel, at):
		raise frappe.PermissionError(
			"Parent Contact Authority is missing, expired, revoked, or channel-limited"
		)


def validate_action_command(
	action_type: str, *, student: str, inputs: dict, actor_roles: set[str], at=None
) -> ActionPolicy:
	require_parent_contact_authority(action_type, student, inputs.get("channel"), at)
	policy = policy_for(action_type)
	missing = [field for field in policy.required_inputs if not inputs.get(field)]
	if missing:
		raise ValueError(f"Missing required action inputs: {', '.join(missing)}")
	if not actor_roles.intersection(policy.actors) and "System Manager" not in actor_roles:
		raise frappe.PermissionError("Actor is not permitted for this action")
	return policy


def allowed_generation_actions(student: str) -> list[str]:
	"""Return the canonical action taxonomy available to recommendation generation.

	The list is intentionally catalog-driven. Runtime dispatch still consults
	``ACTION_POLICIES`` and fails closed for types without an execution contract.
	"""
	return list(available_action_types())


def allowed_operations(action, *, actor_roles: set[str]) -> list[dict]:
	"""Derive card affordances from the current Frappe action, never its type alone."""
	from crm.fcrm.nba import get_nba_action_definition, nba_action_allowed_actors

	action_code = action.get("action") or action.get("action_type")
	known = action_code in ACTION_POLICIES
	state = action.state
	admin = "System Manager" in actor_roles or frappe.session.user == "Administrator"
	nba_definition = get_nba_action_definition(action)
	nba_enabled = not nba_definition or bool(nba_definition.get("enabled"))
	nba_actor_allowed = (
		nba_definition is None
		or admin
		or bool(actor_roles.intersection(nba_action_allowed_actors(nba_definition)))
	)
	nba_auto_execute = bool(nba_definition and nba_definition.get("auto_execute"))
	owner_or_manager = admin or bool(action.action_owner and frappe.db.get_value(
		"CRM Staff", {"user": frappe.session.user}, "name") == action.action_owner)
	package_revision = int(action.execution_package_version or 0)
	action_revision = int(action.action_revision or 1)
	result = []
	for operation in ACTION_OPERATIONS:
		allowed = known and bool(action.has_permission("read")) and nba_enabled and nba_actor_allowed
		reason = "OK"
		requires_approval = False
		if not nba_enabled:
			allowed, reason = False, "NBA_ACTION_DISABLED"
		elif not nba_actor_allowed:
			allowed, reason = False, "NBA_ACTOR_NOT_ALLOWED"
		elif not known:
			allowed, reason = False, "UNKNOWN_ACTION_TYPE"
		elif operation == "EDIT":
			pii_ready = frappe.conf.get("crm_action_pii_controls_enabled", 0) in (1, "1", True)
			allowed = pii_ready and action_code in {"EMAIL", "SEND_EMAIL"} and state in {"accepted", "in-progress"} and owner_or_manager
			reason = "OK" if allowed else "EDIT_NOT_AVAILABLE"
		elif operation == "DISPATCH":
			pii_ready = frappe.conf.get("crm_action_pii_controls_enabled", 0) in (1, "1", True)
			allowed = pii_ready and state in {"accepted", "in-progress"} and owner_or_manager and action_code != "HANDOFF"
			requires_approval = bool(action.risk_tier == "high" or (nba_definition and nba_definition.get("requires_approval"))) and not nba_auto_execute
			reason = "REQUIRES_APPROVAL" if allowed and requires_approval else "OK" if allowed else "DISPATCH_NOT_AVAILABLE"
		elif operation == "SCHEDULE":
			allowed = state in {"accepted", "in-progress"} and owner_or_manager
			reason = "OK" if allowed else "SCHEDULE_NOT_AVAILABLE"
		elif operation == "ASSIGN":
			allowed = state not in {"completed", "cancelled", "rejected", "superseded"} and (admin or "Lead Sales" in actor_roles)
			reason = "OK" if allowed else "ASSIGN_NOT_AVAILABLE"
		elif operation == "RELEASE":
			allowed = state not in {"completed", "cancelled", "rejected", "superseded"} and owner_or_manager
			reason = "OK" if allowed else "RELEASE_NOT_AVAILABLE"
		elif operation == "RECORD_OUTCOME":
			allowed = state in {"accepted", "in-progress"} and owner_or_manager
			reason = "OK" if allowed else "OUTCOME_NOT_AVAILABLE"
		result.append({
			"operation": operation, "state": "allowed" if allowed else "denied",
			"reason_code": reason, "requires_approval": requires_approval,
			"auto_execute": nba_auto_execute,
			"expected_action_revision": action_revision,
			"expected_package_revision": package_revision,
		})
	return result
