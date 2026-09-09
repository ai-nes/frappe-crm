"""Command service for Segment-scoped CRM Action Items."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

from crm.fcrm.action_type_catalog import action_category
from crm.fcrm.student_decision import POLICY_VERSION, compute_risk_tier

CANONICAL_ACTION = "CRM Action Item"
SEGMENT_ACTION_TYPE = "CREATE_TASK"
TERMINAL_STATES = {"completed", "cancelled", "superseded", "rejected"}


def _required(value: Any, label: str) -> str:
	if value in (None, "") or not str(value).strip():
		frappe.throw(_("{0} is required.").format(label), frappe.ValidationError)
	return str(value).strip()


def _actor() -> str:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	return actor


def _segment(segment: str, permission_type: str = "read"):
	segment = _required(segment, "segment")
	if not frappe.db.exists("CRM Segment", segment):
		frappe.throw(_("Segment not found"), frappe.DoesNotExistError)
	doc = frappe.get_doc("CRM Segment", segment)
	doc.check_permission(permission_type)
	return doc


def _priority(value: str | None) -> str:
	priority = str(value or "medium").strip().lower()
	if priority not in {"low", "medium", "high"}:
		frappe.throw(_("Unsupported Action priority."), frappe.ValidationError)
	return priority


def _state(value: str | None, default: str = "pending") -> str:
	state = str(value or default).strip().lower()
	if state not in {"pending", "accepted", "in-progress", "completed", "cancelled"}:
		frappe.throw(_("Unsupported initial Action state."), frappe.ValidationError)
	return state


def _validate_assignee(staff: str | None) -> None:
	if not staff:
		return
	row = frappe.db.get_value("CRM Staff", staff, ["user", "is_active"], as_dict=True)
	if not row:
		frappe.throw(_("The selected executor does not exist."), frappe.ValidationError)
	if row.get("is_active") in (0, "0", False):
		frappe.throw(_("The selected executor is inactive."), frappe.ValidationError)
	if not row.get("user"):
		frappe.throw(_("The selected executor is not mapped to a User."), frappe.ValidationError)


def _fingerprint(payload: dict[str, Any]) -> str:
	return hashlib.sha256(
		json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode()
	).hexdigest()


def _execution_status(state: str) -> str:
	return {
		"completed": "completed",
		"in-progress": "in_progress",
		"cancelled": "cancelled",
	}.get(state, "planned")


def _task_result(action, status: str) -> dict[str, Any]:
	return {
		"status": status,
		"action": action.name,
		"segment": action.segment,
		"revision": int(action.get("action_revision") or 1),
	}


def create_segment_action_item(
	segment: str,
	*,
	title: str,
	description: str | None = None,
	start_date: Any = None,
	priority: str | None = None,
	due_at: Any = None,
	assignee_staff: str | None = None,
	linked_interaction: str | None = None,
	initial_state: str | None = None,
	idempotency_key: str,
):
	"""Create a Segment-scoped CRM Action Item, never a Frappe Task."""
	actor = _actor()
	segment_doc = _segment(segment, "read")
	objective = _required(title, "objective")[:500]
	priority = _priority(priority)
	state = _state(initial_state)
	_validate_assignee(assignee_staff)
	command_key = _required(idempotency_key, "idempotency_key")
	payload = {
		"segment": segment_doc.name,
		"title": objective,
		"description": description,
		"start_date": start_date,
		"priority": priority,
		"due_at": due_at,
		"assignee_staff": assignee_staff,
		"linked_interaction": linked_interaction,
		"initial_state": state,
	}
	fingerprint = _fingerprint(payload)
	now = now_datetime()
	action = frappe.get_doc(
		{
			"doctype": CANONICAL_ACTION,
			"segment": segment_doc.name,
			"origin": "manual",
			"action": SEGMENT_ACTION_TYPE,
			"action_type": action_category(SEGMENT_ACTION_TYPE),
			"objective": objective,
			"description": description,
			"start_date": start_date,
			"disposition": "ACT",
			"state": state,
			"execution_status": _execution_status(state),
			"priority": priority,
			"risk_tier": compute_risk_tier(SEGMENT_ACTION_TYPE),
			"due_at": due_at,
			"action_owner": assignee_staff,
			"source_context_revision": 0,
			"policy_context_version": POLICY_VERSION,
			"generation_idempotency_key": command_key,
			"producer_identity": f"user:{actor}",
			"payload_digest": fingerprint,
			"linked_interaction": linked_interaction,
			"action_revision": 1,
			"decision_revision": 1,
			"accepted_at": now if state != "pending" else None,
			"completed_at": now if state == "completed" else None,
			"created_at": now,
		}
	)
	previous_flag = getattr(frappe.flags, "crm_action_command", False)
	frappe.flags.crm_action_command = True
	try:
		action.insert(ignore_permissions=True)
	finally:
		frappe.flags.crm_action_command = previous_flag
	return _task_result(action, "accepted" if state == "accepted" else state)


def update_segment_action_item(
	name: str,
	*,
	title: str | None = None,
	description: str | None = None,
	start_date: Any = None,
	priority: str | None = None,
	due_at: Any = None,
	assignee_staff: str | None = None,
	action_state: str | None = None,
	linked_interaction: str | None = None,
):
	"""Update a Segment-scoped CRM Action Item through its command boundary."""
	_actor()
	action = frappe.get_doc(CANONICAL_ACTION, name)
	if not action.get("segment") or action.get("student"):
		frappe.throw(_("This Action Item is not Segment-scoped."), frappe.ValidationError)
	_segment(action.segment, "write")
	if priority is not None:
		priority = _priority(priority)
	if action_state is not None:
		action_state = _state(action_state)
	if assignee_staff is not None:
		_validate_assignee(assignee_staff)
	previous_flag = getattr(frappe.flags, "crm_action_command", False)
	previous_compatibility_flag = getattr(frappe.flags, "crm_action_compatibility_command", False)
	frappe.flags.crm_action_command = True
	frappe.flags.crm_action_compatibility_command = True
	try:
		if title is not None:
			action.objective = _required(title, "title")[:500]
		if description is not None:
			action.description = description
		if start_date is not None:
			action.start_date = start_date
		if priority is not None:
			action.priority = priority
		if due_at is not None:
			action.due_at = due_at
		if assignee_staff is not None:
			action.action_owner = assignee_staff
		if linked_interaction is not None:
			action.linked_interaction = linked_interaction
		if action_state is not None:
			action.state = action_state
			action.execution_status = _execution_status(action.state)
			if action.state == "in-progress" and not action.started_at:
				action.started_at = now_datetime()
			if action.state == "completed":
				action.completed_at = now_datetime()
			if action.state in TERMINAL_STATES:
				action.terminal_reason = "Updated through the Segment Action Item command."
		action.action_revision = int(action.get("action_revision") or 1) + 1
		action.decision_actor = frappe.session.user
		action.decision_at = now_datetime()
		action.save(ignore_permissions=True)
	finally:
		frappe.flags.crm_action_command = previous_flag
		frappe.flags.crm_action_compatibility_command = previous_compatibility_flag
	return _task_result(action, "updated")


def delete_segment_action_item(name: str):
	"""Soft-delete a Segment-scoped CRM Action Item and preserve its audit row."""
	_actor()
	action = frappe.get_doc(CANONICAL_ACTION, name)
	if not action.get("segment") or action.get("student"):
		frappe.throw(_("This Action Item is not Segment-scoped."), frappe.ValidationError)
	_segment(action.segment, "write")
	previous_flag = getattr(frappe.flags, "crm_action_command", False)
	previous_compatibility_flag = getattr(frappe.flags, "crm_action_compatibility_command", False)
	frappe.flags.crm_action_command = True
	frappe.flags.crm_action_compatibility_command = True
	try:
		if action.state not in TERMINAL_STATES:
			action.state = "cancelled"
			action.execution_status = "cancelled"
			action.terminal_reason = "Deleted through the Segment Action Item command."
		action.legacy_task_deleted = 1
		action.action_revision = int(action.get("action_revision") or 1) + 1
		action.decision_actor = frappe.session.user
		action.decision_at = now_datetime()
		action.save(ignore_permissions=True)
	finally:
		frappe.flags.crm_action_command = previous_flag
		frappe.flags.crm_action_compatibility_command = previous_compatibility_flag
	return {"deleted": name}
