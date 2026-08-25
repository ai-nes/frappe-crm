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

ALLOWED_ACTIONS = {"WAIT", "CALL", "EMAIL", "FOLLOW_UP", "EVENT_INVITE", "COUNSELING", "HANDOFF"}
PRODUCER_FLAG = "phase6_recommendation_producer"


def _fingerprint(values: dict[str, Any]) -> str:
	return hashlib.sha256(json.dumps(values, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _service_identity() -> str:
	identity = frappe.conf.get("crm_recommendation_producer_id")
	if not identity:
		frappe.throw(_("Recommendation producer is not configured."), frappe.PermissionError)
	return str(identity)


def produce_recommendation(*, student: str, rule_key: str, source_intent_id: str, recommended_action: str, priority: str = "medium", reason: str, evidence: Any = None, recommended_timing: Any = None, condition_version: int = 1, policy_version: str = "phase6-v1", producer_revision: int = 1):
	"""Create-or-return a deterministic, server-authenticated recommendation."""
	if recommended_action not in ALLOWED_ACTIONS:
		frappe.throw(_("Unsupported recommendation action."), frappe.ValidationError)
	producer_id = _service_identity()
	payload = {"student": student, "rule_key": rule_key, "source_intent_id": source_intent_id, "recommended_action": recommended_action, "condition_version": int(condition_version), "policy_version": policy_version, "producer_revision": int(producer_revision)}
	context_hash = _fingerprint(payload)
	existing = frappe.db.get_value("CRM Recommendation", {"student": student, "rule_key": rule_key, "source_intent_id": source_intent_id, "condition_version": int(condition_version), "context_hash": context_hash}, "name")
	if existing:
		return frappe.get_doc("CRM Recommendation", existing)
	doc = frappe.get_doc({"doctype": "CRM Recommendation", **payload, "context_hash": context_hash, "producer_id": producer_id, "priority": priority, "status": "new", "created_at": frappe.utils.now_datetime(), "recommended_timing": recommended_timing, "reason": reason, "evidence": evidence})
	doc.flags.from_phase6_command = True
	doc.insert(ignore_permissions=True)
	return doc
