"""Server-only factory for canonical Recommendation rows.

External callers must be adapted to this boundary; it intentionally does not
trust a caller supplied author, actor, or arbitrary document fields.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _

from crm.fcrm.action_type_catalog import (
	SUPPORTED_RECOMMENDATION_ACTION_TYPES,
	canonicalize_action_type,
)
from crm.fcrm.action_type_registry import is_available_action_type
from crm.fcrm.nba_timing import is_time_allowed

ALLOWED_ACTIONS = SUPPORTED_RECOMMENDATION_ACTION_TYPES
PRODUCER_FLAG = "phase6_recommendation_producer"


def _fingerprint(values: dict[str, Any]) -> str:
	return hashlib.sha256(json.dumps(values, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _service_identity() -> str:
	identity = frappe.conf.get("crm_recommendation_producer_id")
	if not identity:
		frappe.throw(_("Recommendation producer is not configured."), frappe.PermissionError)
	return str(identity)


def produce_recommendation(
	*,
	student: str,
	rule_key: str,
	source_intent_id: str,
	recommended_action: str,
	priority: str = "medium",
	reason: str,
	evidence: Any = None,
	recommended_timing: Any = None,
	timing_policy: str | None = None,
	trigger: str | None = None,
	expires_at: Any = None,
	cta: str | None = None,
	talking_points: Any = None,
	condition_version: int = 1,
	policy_version: str = "phase6-v1",
	producer_revision: int = 1,
):
	"""Create-or-return a deterministic, server-authenticated recommendation."""
	recommended_action = canonicalize_action_type(recommended_action)
	if recommended_action not in ALLOWED_ACTIONS and not is_available_action_type(recommended_action):
		frappe.throw(_("Unsupported recommendation action."), frappe.ValidationError)
	if recommended_action not in {"WAIT", "FOLLOW_UP"} and not is_available_action_type(recommended_action):
		frappe.throw(_("CRM Action Type is disabled or unavailable."), frappe.ValidationError)
	producer_id = _service_identity()
	serialized_talking_points = (
		json.dumps(talking_points, ensure_ascii=False)
		if isinstance(talking_points, (list, dict))
		else talking_points
	)
	serialized_evidence = (
		json.dumps(evidence, ensure_ascii=False) if isinstance(evidence, (list, dict)) else evidence
	)
	payload = {
		"student": student,
		"rule_key": rule_key,
		"source_intent_id": source_intent_id,
		"recommended_action": recommended_action,
		"condition_version": int(condition_version),
		"policy_version": policy_version,
		"producer_revision": int(producer_revision),
		"expires_at": expires_at,
		"timing_policy": timing_policy,
		"trigger": trigger,
		"cta": cta,
		"talking_points": serialized_talking_points,
	}
	context_hash = _fingerprint(payload)
	existing = frappe.db.get_value("CRM Recommendation", {"student": student, "rule_key": rule_key, "source_intent_id": source_intent_id, "condition_version": int(condition_version), "context_hash": context_hash}, "name")
	if existing:
		return frappe.get_doc("CRM Recommendation", existing)
	from crm.fcrm.nba import (
		TIMING_POLICY_DOCTYPE,
		ensure_nba_action,
		get_nba_action_definition,
		resolve_nba_channel,
	)
	canonical_action_type = recommended_action if is_available_action_type(recommended_action) else None
	if timing_policy:
		if not frappe.db.exists(TIMING_POLICY_DOCTYPE, timing_policy):
			frappe.throw(_("CRM Timing Policy does not exist."), frappe.ValidationError)
	action_name = ensure_nba_action(canonical_action_type)
	definition = get_nba_action_definition({"nba_action": action_name}) if action_name else None
	now = frappe.utils.now_datetime()
	if definition and definition.get("allowed_time_slots"):
		try:
			if not is_time_allowed(recommended_timing or now, definition.get("allowed_time_slots")):
				frappe.throw(
					_("{0} is outside its configured allowed time window.").format(recommended_action),
					frappe.ValidationError,
					title="ACTION_TIME_WINDOW",
				)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)
	doc = frappe.get_doc(
		{
			"doctype": "CRM Recommendation",
			"student": student,
			"rule_key": rule_key,
			"source_intent_id": source_intent_id,
			"recommended_action": recommended_action,
			"condition_version": int(condition_version),
			"policy_version": policy_version,
			"producer_revision": int(producer_revision),
			"expires_at": expires_at,
			"cta": cta,
			"talking_points": serialized_talking_points,
			"context_hash": context_hash,
			"producer_id": producer_id,
			"priority": priority,
			"status": "new",
			"created_at": now,
			"recommended_timing": recommended_timing,
			"recommended_at": now,
			"target_type": "CRM Student",
			"target_id": student,
			"action": action_name,
			"purpose": reason,
			"channel": resolve_nba_channel(
				{"action_type": canonical_action_type, "nba_action": action_name},
				definition.get("default_channel") if definition else None,
			),
			"trigger": trigger or rule_key,
			"timing_policy": timing_policy,
			"owner": frappe.db.get_value("CRM Student", student, "owner_staff"),
			"lifecycle_status": "proposed",
			"decision_status": "pending",
			"execution_status": "not_started",
			"reason": reason,
			"evidence": serialized_evidence,
		}
	)
	doc.flags.from_phase6_command = True
	doc.insert(ignore_permissions=True)
	return doc
