"""Shared validation and serialization for the Frappe-owned CRM Rule registry."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

RULE_SCHEMA_VERSION = "crm-rule-v1"
MAX_CONDITION_DEPTH = 8
MAX_CONDITION_NODES = 50
MAX_TARGET_ACTIONS = 20

FEATURE_SCOPES = frozenset({"all", "intent", "student_360", "scoring", "nba", "copilot"})
RULE_TYPES = frozenset({"GUARDRAIL", "ELIGIBILITY", "PREREQUISITE", "MODIFIER", "RESOLUTION"})
GATE_OUTCOMES = frozenset({"PASS", "WAIT", "STOP"})
STATUSES = frozenset({"draft", "published", "archived"})
OPERATORS = frozenset(
	{
		"eq",
		"neq",
		"in",
		"not_in",
		"exists",
		"gt",
		"gte",
		"lt",
		"lte",
		"before",
		"after",
		"is_true",
		"is_false",
	}
)
NO_VALUE_OPERATORS = frozenset({"exists", "is_true", "is_false"})
COMPARISON_OPERATORS = frozenset({"eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "before", "after"})
RULE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
ACTION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")

# This catalog is the boundary between the CRM data model and the AI rule
# evaluator. Adding a fact is a contract change; arbitrary database paths are
# deliberately not accepted from an administrator-edited JSON value.
FACT_CATALOG = {
	"student.stage": {"type": "string"},
	"student.lifecycle_stage": {"type": "string"},
	"student.is_opted_out": {"type": "boolean"},
	"student.email_bounced": {"type": "boolean"},
	"application.status": {"type": "string"},
	"application.document_total": {"type": "number"},
	"application.document_completed": {"type": "number"},
	"application.deadline": {"type": "datetime"},
	"interaction.has_new_content": {"type": "boolean"},
	"interaction.last_analyzed_at": {"type": "datetime"},
	"student_360.last_generated_at": {"type": "datetime"},
	"student_360.source_revision": {"type": "number"},
	"score.last_computed_at": {"type": "datetime"},
	"score.source_revision": {"type": "number"},
	"activity.last_contact_at": {"type": "datetime"},
	"activity.contact_count_7d": {"type": "number"},
	"requested_action.code": {"type": "string"},
	"requested_action.category": {"type": "string"},
	"requested_action.channel": {"type": "string"},
	"system.now": {"type": "datetime"},
}


def _parse_json(value: Any, fieldname: str, default: Any) -> Any:
	if value in (None, ""):
		return default
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError) as exc:
			raise ValueError(f"{fieldname} must be valid JSON.") from exc
	return value


def _validate_json_value(value: Any, fieldname: str) -> None:
	try:
		encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
	except (TypeError, ValueError) as exc:
		raise ValueError(f"{fieldname} contains a non-JSON value.") from exc
	if len(encoded) > 4000:
		raise ValueError(f"{fieldname} exceeds the maximum size.")


def _normalize_condition_node(node: Any, *, depth: int, counter: list[int]) -> dict:
	if depth > MAX_CONDITION_DEPTH:
		raise ValueError(f"condition nesting cannot exceed {MAX_CONDITION_DEPTH} levels.")
	if not isinstance(node, Mapping):
		raise ValueError("Each condition node must be a JSON object.")
	counter[0] += 1
	if counter[0] > MAX_CONDITION_NODES:
		raise ValueError(f"condition cannot contain more than {MAX_CONDITION_NODES} nodes.")

	if "not" in node:
		if set(node) != {"not"}:
			raise ValueError("A 'not' condition cannot contain sibling keys.")
		return {"not": _normalize_condition_node(node["not"], depth=depth + 1, counter=counter)}

	branch_keys = [key for key in ("all", "any") if key in node]
	if branch_keys:
		if set(node) != set(branch_keys):
			raise ValueError("A condition group may only contain 'all' and/or 'any'.")
		result = {}
		for key in branch_keys:
			children = node[key]
			if not isinstance(children, list):
				raise ValueError(f"condition.{key} must be a list.")
			result[key] = [
				_normalize_condition_node(child, depth=depth + 1, counter=counter)
				for child in children
			]
		if not any(result.values()):
			raise ValueError("A condition group must contain at least one node.")
		return result

	allowed_keys = {"fact", "op", "value", "fact_ref"}
	if set(node) - allowed_keys:
		raise ValueError("A condition contains an unsupported key.")
	fact = node.get("fact")
	op = node.get("op")
	if fact not in FACT_CATALOG:
		raise ValueError(f"Fact '{fact}' is not allowed in CRM Rule conditions.")
	if op not in OPERATORS:
		raise ValueError(f"Operator '{op}' is not supported by CRM Rule conditions.")
	if "fact_ref" in node and node["fact_ref"] not in FACT_CATALOG:
		raise ValueError(f"Fact reference '{node['fact_ref']}' is not allowed.")
	if op in NO_VALUE_OPERATORS and ("value" in node or "fact_ref" in node):
		raise ValueError(f"Operator '{op}' does not accept value or fact_ref.")
	if "value" in node and "fact_ref" in node:
		raise ValueError("A condition cannot contain both value and fact_ref.")
	if op in COMPARISON_OPERATORS and "value" not in node and "fact_ref" not in node:
		raise ValueError(f"Operator '{op}' requires value or fact_ref.")
	if op in {"in", "not_in"} and (
		not isinstance(node.get("value"), list) or not node["value"]
	):
		raise ValueError(f"Operator '{op}' requires a non-empty list value.")
	if "value" in node:
		_validate_json_value(node["value"], "condition.value")

	result = {"fact": fact, "op": op}
	if "value" in node:
		result["value"] = node["value"]
	if "fact_ref" in node:
		result["fact_ref"] = node["fact_ref"]
	return result


def normalize_condition(value: Any) -> dict:
	condition = _parse_json(value, "condition", {})
	if not isinstance(condition, Mapping) or not condition:
		raise ValueError("condition must be a non-empty bounded JSON AST.")
	return _normalize_condition_node(condition, depth=0, counter=[0])


def normalize_target_actions(value: Any) -> list[str]:
	actions = _parse_json(value, "target_actions", [])
	if not isinstance(actions, list):
		raise ValueError("target_actions must be a JSON array.")
	if len(actions) > MAX_TARGET_ACTIONS:
		raise ValueError(f"target_actions cannot contain more than {MAX_TARGET_ACTIONS} items.")
	normalized = []
	for action in actions:
		if not isinstance(action, str) or not ACTION_PATTERN.fullmatch(action.strip().upper()):
			raise ValueError("target_actions must contain bounded uppercase action codes.")
		normalized.append(action.strip().upper())
	if len(normalized) != len(set(normalized)):
		raise ValueError("target_actions cannot contain duplicates.")
	return normalized


def _text(value: Any, fieldname: str, *, max_length: int = 140) -> str:
	value = str(value or "").strip()
	if not value:
		raise ValueError(f"{fieldname} is required.")
	if len(value) > max_length:
		raise ValueError(f"{fieldname} exceeds the maximum length.")
	return value


def _as_bool(value: Any) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def normalize_rule_data(value: Mapping[str, Any]) -> dict:
	if not isinstance(value, Mapping):
		raise ValueError("CRM Rule data must be an object.")
	rule_id = _text(value.get("rule_id"), "rule_id", max_length=64).upper()
	if not RULE_ID_PATTERN.fullmatch(rule_id):
		raise ValueError("rule_id must match ^[A-Z][A-Z0-9_-]{2,63}$.")
	rule_group = _text(value.get("rule_group"), "rule_group", max_length=80).upper()
	rule_name = _text(value.get("rule_name"), "rule_name", max_length=140)
	feature_scope = _text(value.get("feature_scope"), "feature_scope", max_length=40).lower()
	if feature_scope not in FEATURE_SCOPES:
		raise ValueError(f"feature_scope must be one of {sorted(FEATURE_SCOPES)}.")
	rule_type = _text(value.get("rule_type"), "rule_type", max_length=30).upper()
	if rule_type not in RULE_TYPES:
		raise ValueError(f"rule_type must be one of {sorted(RULE_TYPES)}.")
	gate_outcome = _text(value.get("gate_outcome"), "gate_outcome", max_length=10).upper()
	if gate_outcome not in GATE_OUTCOMES:
		raise ValueError(f"gate_outcome must be one of {sorted(GATE_OUTCOMES)}.")
	try:
		priority = int(value.get("priority") or 0)
	except (TypeError, ValueError) as exc:
		raise ValueError("priority must be an integer.") from exc
	if priority < 0 or priority > 1000:
		raise ValueError("priority must be between 0 and 1000.")
	action = _text(value.get("action"), "action", max_length=64).upper()
	if not ACTION_PATTERN.fullmatch(action):
		raise ValueError("action must be a bounded uppercase business code.")
	status = _text(value.get("status") or "draft", "status", max_length=20).lower()
	if status not in STATUSES:
		raise ValueError(f"status must be one of {sorted(STATUSES)}.")

	try:
		revision = max(int(value.get("revision") or 0), 0)
	except (TypeError, ValueError) as exc:
		raise ValueError("revision must be a non-negative integer.") from exc

	return {
		"rule_id": rule_id,
		"rule_group": rule_group,
		"rule_name": rule_name,
		"description": str(value.get("description") or "").strip()[:2000],
		"feature_scope": feature_scope,
		"rule_type": rule_type,
		"gate_outcome": gate_outcome,
		"priority": priority,
		"action": action,
		"target_actions": normalize_target_actions(value.get("target_actions")),
		"condition": normalize_condition(value.get("condition")),
		"enabled": _as_bool(value.get("enabled")),
		"status": status,
		"revision": revision,
		"schema_version": RULE_SCHEMA_VERSION,
	}


def canonical_rule_payload(row: Mapping[str, Any]) -> dict:
	"""Return the stable wire representation consumed by ``ai-crm``."""
	data = normalize_rule_data(row)
	data.pop("status", None)
	data.pop("enabled", None)
	data["rule_digest"] = hashlib.sha256(
		json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	).hexdigest()
	return data


def active_rule_catalog(rows: list[Mapping[str, Any]], feature_scope: str | None = None) -> dict:
	"""Build a deterministic, digest-bound catalog from published rows."""
	items = []
	for row in rows:
		payload = canonical_rule_payload(row)
		if feature_scope and payload["feature_scope"] not in {feature_scope, "all"}:
			continue
		items.append(payload)
	items.sort(key=lambda item: (-item["priority"], item["rule_id"], item["revision"]))
	digest = hashlib.sha256(
		json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	).hexdigest()
	max_revision = max((item["revision"] for item in items), default=0)
	return {
		"schema_version": RULE_SCHEMA_VERSION,
		"ruleset_revision": f"crm-rule-set-r{max_revision}-{digest[:12]}",
		"ruleset_digest": digest,
		"feature_scope": feature_scope,
		"rules": items,
	}


def fact_metadata() -> list[dict[str, Any]]:
	return [{"fact": fact, **metadata} for fact, metadata in sorted(FACT_CATALOG.items())]
