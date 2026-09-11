"""Validation and canonical serialization for the Frappe rule control plane."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any

from crm.fcrm.action_type_catalog import ACTION_TYPE_CATALOG

RULE_SCHEMA_VERSION = "rule-catalog"
CATALOG_SCHEMA = RULE_SCHEMA_VERSION
RUNTIME_FEATURES = (
	"conversation_analysis",
	"student_360",
	"school_360",
	"nba",
	"copilot",
)
FEATURE_SCOPES = frozenset({"all", *RUNTIME_FEATURES})
CATALOG_FEATURES = frozenset(RUNTIME_FEATURES)
RULE_TYPES = frozenset({"GUARDRAIL", "ELIGIBILITY", "PREREQUISITE", "MODIFIER", "RESOLUTION"})
GATE_OUTCOMES = frozenset({"PASS", "WAIT", "STOP", "DIRECT", "ESCALATE"})
OUTCOMES = GATE_OUTCOMES
STATUSES = frozenset({"draft", "testing", "active", "archived"})
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
COMPARISON_OPERATORS = OPERATORS - NO_VALUE_OPERATORS
VERSION_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9._-]{1,63}$")
RULE_ID_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
ACTION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_-]{1,63}$")
GROUP_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
TEMPLATE_TOKEN_PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}")
SAFE_TEMPLATE_TOKENS = frozenset({"action", "fact_label", "rule_name"})
DEFAULT_SALES_NEXT_STEP = "Chưa có bước tiếp theo được xác định."
PII_LITERAL_PATTERNS = (
	re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b"),
	re.compile(r"(?<!\d)\+?\d[\d\s().-]{6,}\d(?!\d)"),
)
MAX_CONDITION_DEPTH = 8
MAX_CONDITION_NODES = 50
MAX_TARGET_ACTIONS = 30
MAX_RULES = 500
MAX_GROUPS = 50
EXPLANATION_FIELDS = frozenset(
	{
		"reason_codes",
		"business_reason",
		"sales_next_step",
		"affected_actions",
		"matched_rule_ids",
		"rule_version",
		"rule_version_digest",
		"ruleset_digest",
	}
)


# Authoring and runtime intentionally share one closed registry.  Define the
# public mapping after ``FACT_DESCRIPTORS`` below so a draft cannot validate a
# fact that immutable catalog activation would later reject.
FACT_CATALOG: dict[str, dict[str, str]] = {}

# This is deliberately a closed registry. Adding a fact changes the wire
# contract and must be mirrored by crm-agents before an active snapshot can be
# produced.
FACT_DESCRIPTORS = (
	{
		"fact_id": "intent.current",
		"feature": "conversation_analysis",
		"producer": "CRM Intent",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "event_revision",
		"freshness": "event_bound",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["conversation_analysis", "student_360", "nba", "copilot"],
	},
	{
		"fact_id": "student.is_opted_out",
		"feature": "student_360",
		"producer": "CRM Student",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "STOP",
		"pii_class": "restricted",
		"consumers": ["conversation_analysis", "student_360", "school_360", "nba", "copilot"],
	},
	{
		"fact_id": "activity.last_contact_at",
		"feature": "student_360",
		"producer": "CRM Interaction",
		"authority": "frappe",
		"value_type": "datetime",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["student_360", "nba", "copilot"],
	},
	{
		"fact_id": "score.source_revision",
		"feature": "student_360",
		"producer": "CRM Score Rule",
		"authority": "frappe",
		"value_type": "number",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["student_360", "nba", "copilot"],
	},
	{
		"fact_id": "requested_action.code",
		"feature": "nba",
		"producer": "CRM NBA Evaluation",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "snapshot_digest",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba", "copilot"],
	},
	{
		"fact_id": "student.stage",
		"feature": "nba",
		"producer": "CRM Student.student_stage",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["student_360", "nba", "copilot"],
	},
	{
		"fact_id": "student.privacy_restricted",
		"feature": "nba",
		"producer": "privacy projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "STOP",
		"pii_class": "restricted",
		"consumers": ["nba"],
	},
	{
		"fact_id": "contact.consent_state",
		"feature": "nba",
		"producer": "append-only consent events",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "event_revision",
		"freshness": "event_bound",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "contact.recipient_bound",
		"feature": "nba",
		"producer": "contactability projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "contact.call_allowed",
		"feature": "nba",
		"producer": "consent scope projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "contact.email_allowed",
		"feature": "nba",
		"producer": "consent scope projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "contact.message_allowed",
		"feature": "nba",
		"producer": "consent scope projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "contact.email_bounced",
		"feature": "nba",
		"producer": "CRM Student.email_bounced",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "application.exists",
		"feature": "nba",
		"producer": "Application projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "application.status",
		"feature": "nba",
		"producer": "Application projection",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "application.completeness",
		"feature": "nba",
		"producer": "document counters",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "application.missing_count",
		"feature": "nba",
		"producer": "document counters",
		"authority": "frappe",
		"value_type": "number",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "application.days_to_deadline",
		"feature": "nba",
		"producer": "application deadline projection",
		"authority": "frappe",
		"value_type": "number",
		"revision_kind": "source_revision",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "assessment.state",
		"feature": "nba",
		"producer": "CRM Student Assessment",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "assessment.interest",
		"feature": "nba",
		"producer": "CRM Student Assessment",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "assessment.fit",
		"feature": "nba",
		"producer": "CRM Student Assessment",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "assessment.primary_barrier",
		"feature": "nba",
		"producer": "CRM Student Assessment",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "academic.gpa_quality",
		"feature": "nba",
		"producer": "academic projection",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "score.freshness",
		"feature": "nba",
		"producer": "score projection",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "activity.has_contact_history",
		"feature": "nba",
		"producer": "latest Interaction",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "activity.days_since_last_contact",
		"feature": "nba",
		"producer": "latest Interaction",
		"authority": "frappe",
		"value_type": "number",
		"revision_kind": "source_revision",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "activity.consecutive_failures",
		"feature": "nba",
		"producer": "Interaction/Outcome history",
		"authority": "frappe",
		"value_type": "number",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "activity.work_in_flight",
		"feature": "nba",
		"producer": "active Action Item",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "sla.state",
		"feature": "nba",
		"producer": "Student SLA evidence",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.channel",
		"feature": "nba",
		"producer": "CRM Action.default_channel",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "snapshot_digest",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.in_candidate_set",
		"feature": "nba",
		"producer": "eligible action set snapshot",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "snapshot_digest",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.enabled",
		"feature": "nba",
		"producer": "CRM Action",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.effective",
		"feature": "nba",
		"producer": "CRM Action",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.actor_allowed",
		"feature": "nba",
		"producer": "governed action projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.requires_approval",
		"feature": "nba",
		"producer": "CRM Action",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.approval_state",
		"feature": "nba",
		"producer": "approval projection",
		"authority": "frappe",
		"value_type": "string",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.requires_parent_authority",
		"feature": "nba",
		"producer": "CRM Action",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.parent_authority_valid",
		"feature": "nba",
		"producer": "parent authority projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.academic_eligible",
		"feature": "nba",
		"producer": "action constraint projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.duplicate_active",
		"feature": "nba",
		"producer": "Action Item history",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "current",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.recently_completed",
		"feature": "nba",
		"producer": "Decision/Action history",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.time_allowed",
		"feature": "nba",
		"producer": "action timing projection",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "source_revision",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "requested_action.alternate_message_available",
		"feature": "nba",
		"producer": "candidate set + consent",
		"authority": "frappe",
		"value_type": "boolean",
		"revision_kind": "snapshot_digest",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "none",
		"consumers": ["nba"],
	},
	{
		"fact_id": "copilot.evidence_state",
		"feature": "copilot",
		"producer": "crm-agents",
		"authority": "crm_agents",
		"value_type": "string",
		"revision_kind": "snapshot_digest",
		"freshness": "bounded",
		"unknown_policy": "WAIT",
		"pii_class": "derived",
		"consumers": ["copilot"],
	},
)

# Keep the legacy ``fact_metadata`` shape for callers, but derive it from the
# same descriptors used by catalog validation and runtime publication.
FACT_CATALOG = {
	item["fact_id"]: {"type": item["value_type"]}
	for item in FACT_DESCRIPTORS
}

# The CRM Action taxonomy is the producer-owned source of truth.  Rule effects
# may target a bounded subset of it, but the catalog must not silently narrow
# valid actions to the smaller MVP subset used by early rule fixtures.
ACTION_CATALOG = tuple(code for code, _display_name, _category in ACTION_TYPE_CATALOG)
# ``SCHEDULE_MEETING`` exists in the first rule-catalog fixtures but is not a
# canonical CRM Action Type. Accept it only as a read-compatible wire value;
# new authoring and CRM Action records remain bound to the 79-code catalog.
LEGACY_ACTION_CODES = frozenset({"SCHEDULE_MEETING"})
ACTION_CODES = frozenset(ACTION_CATALOG) | LEGACY_ACTION_CODES

SURFACE_OUTCOME_MAPPINGS = tuple(
	{
		"surface": surface,
		"outcome": outcome,
		"status": status,
		"disposition": disposition,
		"requires_revisit": requires_revisit,
		"explanation_projection": ["reason_codes", "business_reason", "sales_next_step"],
		"digest_fence": "ruleset_digest",
	}
	for surface, values in (
		(
			"nba",
			(
				("STOP", "completed", "NO_ACTION", False),
				("WAIT", "completed", "WAIT", True),
				("PASS", "completed", "NO_ACTION", False),
				("DIRECT", "completed", "RECOMMEND", False),
				("ESCALATE", "completed", "ABSTAIN", False),
			),
		),
		(
			"analysis_run",
			(
				("STOP", "abstained", None, False),
				("WAIT", "abstained", None, True),
				("PASS", "completed", None, False),
				("DIRECT", "completed", None, False),
				("ESCALATE", "abstained", None, False),
			),
		),
	)
	for outcome, status, disposition, requires_revisit in values
)


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


def normalize_feature_scope(value: Any) -> str:
	feature_scope = _text(value, "feature", max_length=40).lower()
	if feature_scope not in FEATURE_SCOPES:
		raise ValueError(f"feature must be one of {sorted(FEATURE_SCOPES)}.")
	return feature_scope


def _as_bool(value: Any) -> bool:
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def normalize_group_catalog(value: Any) -> list[dict[str, Any]]:
	groups = _parse_json(value, "group_catalog", [])
	if not isinstance(groups, list):
		raise ValueError("group_catalog must be a JSON array.")
	if len(groups) > MAX_GROUPS:
		raise ValueError(f"group_catalog cannot contain more than {MAX_GROUPS} groups.")
	normalized = []
	codes = set()
	for group in groups:
		allowed_keys = {"code", "label", "enabled", "description", "sort_order"}
		if not isinstance(group, Mapping) or set(group) - allowed_keys or not {"code", "label", "enabled"}.issubset(group):
			raise ValueError("Each rule group must contain code, label and enabled.")
		code = _text(group.get("code"), "group code", max_length=40).lower()
		if not GROUP_CODE_PATTERN.fullmatch(code):
			raise ValueError("group code must match ^[a-z][a-z0-9_]{1,39}$.")
		if code in codes:
			raise ValueError("group codes must be unique within a rule version.")
		label = _text(group.get("label"), "group label", max_length=80)
		enabled = group.get("enabled")
		if not isinstance(enabled, bool):
			raise ValueError("group enabled must be a boolean.")
		item = {"code": code, "label": label, "enabled": enabled}
		if "description" in group:
			description = group["description"]
			if description is not None and (not isinstance(description, str) or len(description.strip()) > 240):
				raise ValueError("group description must be a bounded string.")
			if description is not None and description.strip():
				item["description"] = description.strip()
		if "sort_order" in group:
			sort_order = group["sort_order"]
			if isinstance(sort_order, bool) or not isinstance(sort_order, int) or not 0 <= sort_order <= 10000:
				raise ValueError("group sort_order must be a non-negative integer.")
			item["sort_order"] = sort_order
		normalized.append(item)
		codes.add(code)
	return normalized


def _normalize_wire_conditions(value: Any) -> list[dict[str, Any]]:
	conditions = _parse_json(value, "conditions", [])
	if not isinstance(conditions, list) or not conditions:
		raise ValueError("conditions must be a non-empty JSON array.")
	if len(conditions) > MAX_CONDITION_NODES:
		raise ValueError(f"conditions cannot contain more than {MAX_CONDITION_NODES} items.")
	normalized = []
	for condition in conditions:
		if not isinstance(condition, Mapping):
			raise ValueError("Each rule condition must be a JSON object.")
		if set(condition) - {"fact", "operator", "op", "value"}:
			raise ValueError("A rule condition contains an unsupported key.")
		if "operator" in condition and "op" in condition:
			raise ValueError("A rule condition cannot contain both operator and op.")
		fact = condition.get("fact")
		operator = condition.get("operator", condition.get("op"))
		if fact not in FACT_CATALOG:
			raise ValueError(f"Fact '{fact}' is not allowed in CRM Rule conditions.")
		if operator not in OPERATORS:
			raise ValueError(f"Operator '{operator}' is not supported by CRM Rule conditions.")
		has_value = "value" in condition
		if operator in NO_VALUE_OPERATORS and has_value:
			raise ValueError(f"Operator '{operator}' does not accept a value.")
		if operator in COMPARISON_OPERATORS and not has_value:
			raise ValueError(f"Operator '{operator}' requires a value.")
		if operator in {"in", "not_in"} and (
			not isinstance(condition.get("value"), list) or not condition["value"]
		):
			raise ValueError(f"Operator '{operator}' requires a non-empty list value.")
		if has_value:
			_validate_json_value(condition["value"], "conditions.value")
		item = {"fact": fact, "operator": operator}
		if has_value:
			item["value"] = condition["value"]
		normalized.append(item)
	return normalized


def _condition_leaves(condition: Mapping[str, Any]) -> list[dict[str, Any]]:
	"""Adapt the old AST only when it is a conjunction representable on the wire."""
	if "fact" in condition:
		if "fact_ref" in condition:
			raise ValueError("fact_ref conditions are not supported by the current catalog contract.")
		item = {"fact": condition["fact"], "operator": condition["op"]}
		if "value" in condition:
			item["value"] = condition["value"]
		return [item]
	if set(condition) == {"all"}:
		leaves = []
		for child in condition["all"]:
			leaves.extend(_condition_leaves(child))
		return leaves
	raise ValueError("catalog conditions must be a conjunction of leaf conditions.")


def _conditions_to_ast(conditions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
	leaves = []
	for condition in conditions:
		item = {"fact": condition["fact"], "op": condition["operator"]}
		if "value" in condition:
			item["value"] = condition["value"]
		leaves.append(item)
	return {"all": leaves}


def _validate_template(template: Any, fieldname: str) -> str:
	template = _text(template, fieldname, max_length=240)
	if any(ord(char) < 32 for char in template):
		raise ValueError(f"{fieldname} cannot contain control characters.")
	if any(pattern.search(template) for pattern in PII_LITERAL_PATTERNS):
		raise ValueError(f"{fieldname} cannot contain a literal email address or phone number.")
	tokens = TEMPLATE_TOKEN_PATTERN.findall(template)
	if any(token not in SAFE_TEMPLATE_TOKENS for token in tokens):
		raise ValueError(f"{fieldname} contains an unsupported token.")
	if "{" in TEMPLATE_TOKEN_PATTERN.sub("", template) or "}" in TEMPLATE_TOKEN_PATTERN.sub("", template):
		raise ValueError(f"{fieldname} has malformed interpolation.")
	return template


def _validate_business_reason(template: Any) -> str:
	return _validate_template(template, "business_reason_template")


def _validate_sales_next_step(template: Any) -> str:
	return _validate_template(template, "sales_next_step_template")


def normalize_rule_version_data(value: Mapping[str, Any]) -> dict[str, Any]:
	if not isinstance(value, Mapping):
		raise ValueError("CRM Rule Version data must be an object.")
	version_id = _text(value.get("version_id"), "version_id", max_length=64).upper()
	if not VERSION_ID_PATTERN.fullmatch(version_id):
		raise ValueError("version_id must match ^[A-Z][A-Z0-9._-]{1,63}$.")
	version_name = _text(value.get("version_name"), "version_name", max_length=140)
	description = str(value.get("description") or "").strip()
	if len(description) > 2000:
		raise ValueError("description exceeds the maximum length.")
	status = _text(value.get("status") or "draft", "status", max_length=20).lower()
	if status not in STATUSES:
		raise ValueError(f"status must be one of {sorted(STATUSES)}.")
	try:
		revision = int(value.get("revision") or 0)
	except (TypeError, ValueError) as exc:
		raise ValueError("revision must be a non-negative integer.") from exc
	if revision < 0:
		raise ValueError("revision must be a non-negative integer.")
	return {
		"version_id": version_id,
		"version_name": version_name,
		"description": description,
		"status": status,
		"group_catalog": normalize_group_catalog(value.get("group_catalog")),
		"revision": revision,
		"schema_version": RULE_SCHEMA_VERSION,
	}


def normalize_rule_data(value: Mapping[str, Any]) -> dict[str, Any]:
	if not isinstance(value, Mapping):
		raise ValueError("CRM Rule data must be an object.")
	rule_id = _text(value.get("rule_id"), "rule_id", max_length=64).upper()
	if not RULE_ID_PATTERN.fullmatch(rule_id):
		raise ValueError("rule_id must match ^[A-Z][A-Z0-9_-]{2,63}$.")
	rule_version = str(value.get("rule_version") or "").strip().upper()
	if rule_version and not VERSION_ID_PATTERN.fullmatch(rule_version):
		raise ValueError("rule_version must be a valid CRM Rule Version ID.")
	group_value = value.get("group_code") or value.get("rule_group")
	group_code = _text(group_value, "group_code", max_length=40).lower()
	if not GROUP_CODE_PATTERN.fullmatch(group_code):
		raise ValueError("group_code must match ^[a-z][a-z0-9_]{1,39}$.")
	rule_name = _text(value.get("rule_name") or value.get("name"), "name", max_length=140)
	if any(pattern.search(rule_name) for pattern in PII_LITERAL_PATTERNS):
		raise ValueError("name cannot contain a literal email address or phone number.")
	feature_scope = normalize_feature_scope(value.get("feature") or value.get("feature_scope"))
	rule_type = _text(value.get("rule_type"), "rule_type", max_length=30).upper()
	if rule_type not in RULE_TYPES:
		raise ValueError(f"rule_type must be one of {sorted(RULE_TYPES)}.")
	outcome = _text(
		value.get("outcome") or value.get("gate_outcome"),
		"outcome",
		max_length=10,
	).upper()
	if outcome not in OUTCOMES:
		raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}.")
	precedence_value = value.get("precedence", value.get("priority", 0))
	try:
		precedence = int(precedence_value or 0)
	except (TypeError, ValueError) as exc:
		raise ValueError("precedence must be an integer.") from exc
	if precedence < 0 or precedence > 1000:
		raise ValueError("precedence must be between 0 and 1000.")
	target_actions = normalize_target_actions(value.get("target_actions"))
	if "conditions" in value and value.get("conditions") not in (None, ""):
		conditions = _normalize_wire_conditions(value.get("conditions"))
		condition = _conditions_to_ast(conditions)
	else:
		condition = normalize_condition(value.get("condition"))
		conditions = _condition_leaves(condition)
	action = str(value.get("action") or (target_actions[0] if target_actions else "RULE_MATCHED")).strip().upper()
	if not ACTION_PATTERN.fullmatch(action):
		raise ValueError("action must be a bounded uppercase business code.")
	status = _text(value.get("status") or "draft", "status", max_length=20).lower()
	if status not in STATUSES:
		raise ValueError(f"status must be one of {sorted(STATUSES)}.")
	try:
		revision = int(value.get("revision") or 0)
	except (TypeError, ValueError) as exc:
		raise ValueError("revision must be a non-negative integer.") from exc
	if revision < 0:
		raise ValueError("revision must be a non-negative integer.")
	reason_code = _text(value.get("reason_code") or "RULE_MATCHED", "reason_code", max_length=64).upper()
	if not REASON_CODE_PATTERN.fullmatch(reason_code):
		raise ValueError("reason_code must match ^[A-Z][A-Z0-9_]{2,63}$.")
	template = _validate_business_reason(
		value.get("business_reason_template") or "{action} is governed by {rule_name}."
	)
	next_step = _validate_sales_next_step(
		value.get("sales_next_step_template") or DEFAULT_SALES_NEXT_STEP
	)
	unknown_policy = str(value.get("unknown_policy") or "WAIT").strip().upper()
	if unknown_policy not in {"WAIT", "STOP", "PASS"}:
		raise ValueError("unknown_policy must be one of WAIT, STOP or PASS.")
	return {
		"rule_version": rule_version,
		"rule_id": rule_id,
		"group_code": group_code,
		"rule_group": group_code.upper(),
		"name": rule_name,
		"rule_name": rule_name,
		"description": str(value.get("description") or "").strip()[:2000],
		"feature": feature_scope,
		"feature_scope": feature_scope,
		"rule_type": rule_type,
		"outcome": outcome,
		"gate_outcome": outcome,
		"precedence": precedence,
		"priority": precedence,
		"unknown_policy": unknown_policy,
		"reason_code": reason_code,
		"business_reason_template": template,
		"sales_next_step_template": next_step,
		"action": action,
		"target_actions": target_actions,
		"conditions": conditions,
		"condition": condition,
		"enabled": _as_bool(value.get("enabled", True)),
		"status": status,
		"revision": revision,
		"schema_version": RULE_SCHEMA_VERSION,
	}


def canonical_rule_payload(row: Mapping[str, Any]) -> dict[str, Any]:
	"""Return the bounded authoring projection used by compatibility callers."""
	data = normalize_rule_data(row)
	for fieldname in ("rule_version", "status", "enabled"):
		data.pop(fieldname, None)
	data["rule_digest"] = hashlib.sha256(
		json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	).hexdigest()
	return data


def active_rule_catalog(
	rows: list[Mapping[str, Any]],
	feature_scope: str | None = None,
	metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
	"""Compatibility projection for callers not yet moved to the full catalog.

	The control-plane API does not use this helper to select an active version.
	New consumers must use :func:`catalog_from_rows` and the ``rule-catalog``
	contract below.
	"""
	requested_scope = normalize_feature_scope(feature_scope) if feature_scope else None
	items = []
	for row in rows:
		payload = canonical_rule_payload(row)
		if requested_scope and requested_scope != "all" and payload["feature_scope"] not in {
			requested_scope,
			"all",
		}:
			continue
		items.append(payload)
	items.sort(key=lambda item: (-item["precedence"], item["rule_id"], item["revision"]))
	computed_digest = hashlib.sha256(
		json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
	).hexdigest()
	max_revision = max((item["revision"] for item in items), default=0)
	metadata = metadata or {}
	digest = str(metadata.get("ruleset_digest") or computed_digest)
	ruleset_revision = str(
		metadata.get("ruleset_revision") or f"crm-rule-set-r{max_revision}-{computed_digest[:12]}"
	)
	return {
		"schema_version": RULE_SCHEMA_VERSION,
		"version_id": metadata.get("version_id"),
		"version_name": metadata.get("version_name"),
		"ruleset_revision": ruleset_revision,
		"ruleset_digest": digest,
		"feature_scope": requested_scope,
		"rules": items,
	}


def fact_metadata() -> list[dict[str, Any]]:
	return [{"fact": fact, **metadata} for fact, metadata in sorted(FACT_CATALOG.items())]


def fact_descriptors() -> list[dict[str, Any]]:
	return deepcopy(list(FACT_DESCRIPTORS))


def surface_outcome_mappings() -> list[dict[str, Any]]:
	return deepcopy(list(SURFACE_OUTCOME_MAPPINGS))


def _canonical_value(value: Any, *, key: str | None = None) -> Any:
	if isinstance(value, float):
		raise ValueError("floats require an explicit integer/decimal wire representation.")
	if isinstance(value, Mapping):
		return {
			str(item_key): _canonical_value(item_value, key=str(item_key))
			for item_key, item_value in sorted(value.items())
		}
	if isinstance(value, (list, tuple)):
		items = [_canonical_value(item) for item in value]
		if key == "rules":
			return sorted(items, key=lambda item: (-item["precedence"], item["rule_id"]))
		return items
	if value is None or isinstance(value, (str, int, bool)):
		return value
	raise ValueError(f"unsupported canonical JSON value: {type(value).__name__}.")


def _catalog_payload(catalog: Mapping[str, Any]) -> dict[str, Any]:
	payload = deepcopy(dict(catalog))
	payload.pop("ruleset_digest", None)
	for rule in payload.get("rules", []):
		if rule.get("sales_next_step_template") == DEFAULT_SALES_NEXT_STEP:
			rule.pop("sales_next_step_template", None)
		for condition in rule.get("conditions", []):
			if condition.get("value") is None:
				condition.pop("value", None)
	return payload


def _catalog_digest(catalog: Mapping[str, Any]) -> str:
	body = json.dumps(
		_canonical_value(_catalog_payload(catalog)),
		ensure_ascii=False,
		separators=(",", ":"),
	).encode("utf-8")
	return hashlib.sha256(body).hexdigest()


def _validate_condition_value(descriptor: Mapping[str, Any], value: Any) -> None:
	value_type = descriptor["value_type"]
	values = value if isinstance(value, list) else [value]
	for item in values:
		if value_type == "boolean" and not isinstance(item, bool):
			raise ValueError("boolean facts require boolean condition values.")
		if value_type == "number" and (isinstance(item, bool) or not isinstance(item, int)):
			raise ValueError("number facts require integer condition values.")
		if value_type == "string" and not isinstance(item, str):
			raise ValueError("string facts require string condition values.")
		if value_type == "datetime":
			if not isinstance(item, str):
				raise ValueError("datetime facts require RFC3339 condition values.")
			try:
				parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
			except ValueError as exc:
				raise ValueError("datetime condition values must be valid RFC3339.") from exc
			if parsed.tzinfo is None:
				raise ValueError("datetime condition values must include a timezone.")
		if value_type == "string_list" and (
			 not isinstance(item, (list, tuple)) or any(not isinstance(entry, str) for entry in item)
		):
			raise ValueError("string_list facts require string arrays.")


def validate_catalog(payload: Mapping[str, Any]) -> dict[str, Any]:
	"""Validate one complete immutable catalog and bind its canonical digest."""
	if not isinstance(payload, Mapping):
		raise ValueError("rule catalog must be an object.")
	payload = deepcopy(dict(payload))
	required = {
		"schema",
		"rule_version",
		"technical_revision",
		"fact_catalog",
		"action_catalog",
		"rule_groups",
		"rules",
		"surface_outcome_mappings",
	}
	allowed = required | {"ruleset_digest"}
	if set(payload) - allowed or not required.issubset(payload):
		raise ValueError("rule catalog has missing or unsupported fields.")
	if payload.get("schema") != CATALOG_SCHEMA:
		raise ValueError("unsupported rule catalog schema.")
	if not isinstance(payload.get("rule_version"), str) or not payload["rule_version"].strip():
		raise ValueError("rule_version is required.")
	if not isinstance(payload.get("technical_revision"), int) or isinstance(
		payload["technical_revision"], bool
	) or payload["technical_revision"] < 0:
		raise ValueError("technical_revision must be a non-negative integer.")

	facts = payload["fact_catalog"]
	actions = payload["action_catalog"]
	groups = payload["rule_groups"]
	rules = payload["rules"]
	mappings = payload["surface_outcome_mappings"]
	if not all(isinstance(value, list) for value in (facts, actions, groups, rules, mappings)):
		raise ValueError("catalog registries must be arrays.")
	if not facts or not actions or not groups:
		raise ValueError("fact, action and group registries cannot be empty.")
	if len(facts) > 100 or len(actions) > 100 or len(groups) > MAX_GROUPS or len(rules) > MAX_RULES:
		raise ValueError("catalog registry exceeds its maximum size.")

	fact_ids = set()
	fact_by_id = {}
	fact_keys = {
		"fact_id",
		"feature",
		"producer",
		"authority",
		"value_type",
		"revision_kind",
		"freshness",
		"unknown_policy",
		"pii_class",
		"consumers",
	}
	for fact in facts:
		if not isinstance(fact, Mapping) or set(fact) != fact_keys:
			raise ValueError("fact descriptor has an invalid shape.")
		fact_id = fact.get("fact_id")
		if (
			not isinstance(fact_id, str)
			or not re.fullmatch(r"^[a-z][a-z0-9_.]{2,80}$", fact_id)
			or fact_id in fact_ids
		):
			raise ValueError("fact descriptor has an invalid or duplicate fact_id.")
		if fact["feature"] not in CATALOG_FEATURES:
			raise ValueError("fact descriptor uses an unsupported feature.")
		if fact["authority"] not in {"frappe", "crm_agents"}:
			raise ValueError("fact descriptor uses an unsupported authority.")
		if fact["value_type"] not in {"boolean", "number", "string", "datetime", "string_list"}:
			raise ValueError("fact descriptor uses an unsupported value type.")
		if fact["revision_kind"] not in {"source_revision", "snapshot_digest", "event_revision"}:
			raise ValueError("fact descriptor uses an unsupported revision kind.")
		if fact["freshness"] not in {"current", "event_bound", "bounded"}:
			raise ValueError("fact descriptor uses an unsupported freshness value.")
		if fact["unknown_policy"] not in {"WAIT", "STOP", "PASS"}:
			raise ValueError("fact descriptor uses an unsupported unknown policy.")
		if fact["pii_class"] not in {"none", "derived", "restricted"}:
			raise ValueError("fact descriptor uses an unsupported PII class.")
		consumers = fact["consumers"]
		if (
			not isinstance(consumers, list)
			or not consumers
			or len(consumers) > len(RUNTIME_FEATURES)
			or not all(isinstance(consumer, str) for consumer in consumers)
			or len(consumers) != len(set(consumers))
			or set(consumers) - CATALOG_FEATURES
		):
			raise ValueError("fact descriptor consumers must be unique supported features.")
		fact_ids.add(fact_id)
		fact_by_id[fact_id] = fact
	if fact_ids - set(FACT_CATALOG):
		raise ValueError("fact catalog must use unique closed fact descriptors.")

	if (
		not all(isinstance(action, str) for action in actions)
		or len(actions) != len(set(actions))
		or set(actions) - ACTION_CODES
	):
		raise ValueError("action catalog must use unique closed action codes.")

	group_codes = set()
	group_by_code = {}
	for group in groups:
		group_keys = {"code", "label", "enabled", "description", "sort_order"}
		if not isinstance(group, Mapping) or set(group) - group_keys or not {"code", "label", "enabled"}.issubset(group):
			raise ValueError("rule group catalog is invalid.")
		code = group.get("code")
		label = group.get("label")
		if (
			not isinstance(code, str)
			or not GROUP_CODE_PATTERN.fullmatch(code)
			or code in group_codes
			or not isinstance(label, str)
			or not 1 <= len(label) <= 80
			or not isinstance(group.get("enabled"), bool)
			or ("description" in group and group["description"] is not None and (not isinstance(group["description"], str) or len(group["description"]) > 240))
			or ("sort_order" in group and (isinstance(group["sort_order"], bool) or not isinstance(group["sort_order"], int) or not 0 <= group["sort_order"] <= 10000))
		):
			raise ValueError("rule group catalog is invalid.")
		group_codes.add(code)
		group_by_code[code] = group

	rule_ids = set()
	rule_keys = {
		"rule_id",
		"group_code",
		"name",
		"feature",
		"rule_type",
		"precedence",
		"unknown_policy",
		"conditions",
		"effect",
		"reason_code",
		"business_reason_template",
		"sales_next_step_template",
		"enabled",
	}
	legacy_rule_keys = rule_keys - {"sales_next_step_template"}
	for rule in rules:
		if not isinstance(rule, Mapping):
			raise ValueError("rule has an invalid shape.")
		if set(rule) == legacy_rule_keys:
			rule = dict(rule)
			rule["sales_next_step_template"] = DEFAULT_SALES_NEXT_STEP
		if set(rule) != rule_keys:
			raise ValueError("rule has an invalid shape.")
		rule_id = rule.get("rule_id")
		if (
			not isinstance(rule_id, str)
			or not RULE_ID_PATTERN.fullmatch(rule_id)
			or rule_id in rule_ids
		):
			raise ValueError("rule has an invalid or duplicate rule_id.")
		group_code = rule.get("group_code")
		if group_code not in group_by_code or not group_by_code[group_code]["enabled"]:
			raise ValueError("rule references a missing or disabled group.")
		if rule.get("feature") not in FEATURE_SCOPES or rule.get("rule_type") not in RULE_TYPES:
			raise ValueError("rule uses an unsupported feature or type.")
		precedence = rule.get("precedence")
		if not isinstance(precedence, int) or isinstance(precedence, bool) or not 0 <= precedence <= 1000:
			raise ValueError("rule precedence must be an integer from 0 through 1000.")
		if rule.get("unknown_policy") not in {"WAIT", "STOP", "PASS"}:
			raise ValueError("rule uses an unsupported unknown policy.")
		conditions = rule.get("conditions")
		if not isinstance(conditions, list) or not 1 <= len(conditions) <= MAX_CONDITION_NODES:
			raise ValueError("rule conditions must be a bounded non-empty array.")
		for condition in conditions:
			if not isinstance(condition, Mapping) or set(condition) - {"fact", "operator", "value"}:
				raise ValueError("rule condition has an invalid shape.")
			fact_id = condition.get("fact")
			operator = condition.get("operator")
			if fact_id not in fact_ids or operator not in OPERATORS:
				raise ValueError("rule condition references an unknown fact or operator.")
			has_value = "value" in condition
			if operator in NO_VALUE_OPERATORS and has_value:
				raise ValueError("presence operators cannot carry a value.")
			if operator in COMPARISON_OPERATORS and not has_value:
				raise ValueError("comparison operators require a value.")
			if operator in {"in", "not_in"} and (
				not isinstance(condition.get("value"), list) or not condition["value"]
			):
				raise ValueError("membership operators require a non-empty list.")
			if has_value:
				_validate_condition_value(fact_by_id[fact_id], condition["value"])
		effect = rule.get("effect")
		if not isinstance(effect, Mapping) or set(effect) != {"outcome", "target_actions"}:
			raise ValueError("rule effect has an invalid shape.")
		outcome = effect.get("outcome")
		target_actions = effect.get("target_actions")
		if outcome not in OUTCOMES or not isinstance(target_actions, list):
			raise ValueError("rule effect is invalid.")
		if (
			len(target_actions) > MAX_TARGET_ACTIONS
			or not all(isinstance(action, str) for action in target_actions)
			or len(target_actions) != len(set(target_actions))
			or set(target_actions) - set(actions)
		):
			raise ValueError("rule effect actions must be unique and declared.")
		if rule["rule_type"] == "RESOLUTION" and outcome not in {"DIRECT", "ESCALATE"}:
			raise ValueError("resolution rules must produce DIRECT or ESCALATE.")
		if rule["rule_type"] != "RESOLUTION" and outcome not in {"PASS", "WAIT", "STOP"}:
			raise ValueError("gate rules must produce PASS, WAIT or STOP.")
		if not isinstance(rule.get("reason_code"), str) or not REASON_CODE_PATTERN.fullmatch(
			str(rule["reason_code"])
		):
			raise ValueError("rule reason_code is invalid.")
		_validate_business_reason(rule.get("business_reason_template"))
		_validate_sales_next_step(rule.get("sales_next_step_template"))
		if not isinstance(rule.get("enabled"), bool):
			raise ValueError("rule enabled must be a boolean.")
		rule_ids.add(rule_id)

	expected_mappings = {
		(surface, outcome)
		for surface in ("nba", "analysis_run")
		for outcome in OUTCOMES
	}
	actual_mappings = set()
	for mapping in mappings:
		mapping_keys = {
			"surface",
			"outcome",
			"status",
			"disposition",
			"requires_revisit",
			"explanation_projection",
			"digest_fence",
		}
		if not isinstance(mapping, Mapping) or set(mapping) != mapping_keys:
			raise ValueError("surface outcome mapping is invalid.")
		key = (mapping.get("surface"), mapping.get("outcome"))
		if key in actual_mappings or key not in expected_mappings:
			raise ValueError("surface outcome mappings must cover every outcome exactly once.")
		if (
			not isinstance(mapping.get("status"), str)
			or not mapping["status"]
			or (
				mapping.get("disposition") is not None
				and not isinstance(mapping["disposition"], str)
			)
			or not isinstance(mapping.get("requires_revisit"), bool)
			or not isinstance(mapping.get("explanation_projection"), list)
			or not mapping["explanation_projection"]
			or not all(isinstance(item, str) for item in mapping["explanation_projection"])
			or set(mapping["explanation_projection"]) - EXPLANATION_FIELDS
			or len(mapping["explanation_projection"]) != len(set(mapping["explanation_projection"]))
			or not isinstance(mapping.get("digest_fence"), str)
			or mapping["digest_fence"] != "ruleset_digest"
		):
			raise ValueError("surface outcome mapping is invalid.")
		actual_mappings.add(key)
	if actual_mappings != expected_mappings:
		raise ValueError("surface outcome mappings must cover every outcome exactly once.")

	digest = _catalog_digest(payload)
	provided_digest = payload.get("ruleset_digest")
	if provided_digest is not None and provided_digest != digest:
		raise ValueError("ruleset_digest does not match the canonical catalog.")
	result = deepcopy(dict(payload))
	result["ruleset_digest"] = digest
	return result


def _wire_rule_payload(row: Mapping[str, Any]) -> dict[str, Any]:
	data = normalize_rule_data(row)
	return {
		"rule_id": data["rule_id"],
		"group_code": data["group_code"],
		"name": data["name"],
		"feature": data["feature"],
		"rule_type": data["rule_type"],
		"precedence": data["precedence"],
		"unknown_policy": data["unknown_policy"],
		"conditions": data["conditions"],
		"effect": {
			"outcome": data["outcome"],
			"target_actions": data["target_actions"],
		},
		"reason_code": data["reason_code"],
		"business_reason_template": data["business_reason_template"],
		"sales_next_step_template": data["sales_next_step_template"],
		"enabled": data["enabled"],
	}


def catalog_from_rows(
	rows: Sequence[Mapping[str, Any]],
	*,
	version_id: str,
	technical_revision: int,
	group_catalog: Any,
) -> dict[str, Any]:
	"""Build and validate the complete wire catalog for one version snapshot."""
	groups = normalize_group_catalog(group_catalog)
	payload = {
		"schema": CATALOG_SCHEMA,
		"rule_version": str(version_id).strip().upper(),
		"technical_revision": technical_revision,
		"fact_catalog": fact_descriptors(),
		"action_catalog": list(ACTION_CATALOG),
		"rule_groups": groups,
		"rules": [_wire_rule_payload(row) for row in rows],
		"surface_outcome_mappings": surface_outcome_mappings(),
	}
	return validate_catalog(payload)


def canonicalize_ruleset(snapshot: Mapping[str, Any]) -> bytes:
	"""Return canonical UTF-8 bytes for a validated complete catalog."""
	catalog = validate_catalog(snapshot)
	return json.dumps(
		_canonical_value(_catalog_payload(catalog)),
		ensure_ascii=False,
		separators=(",", ":"),
	).encode("utf-8")


def ruleset_digest(snapshot: Mapping[str, Any]) -> str:
	return hashlib.sha256(canonicalize_ruleset(snapshot)).hexdigest()


__all__ = [
	"ACTION_CATALOG",
	"CATALOG_SCHEMA",
	"FEATURE_SCOPES",
	"GATE_OUTCOMES",
	"OUTCOMES",
	"RUNTIME_FEATURES",
	"STATUSES",
	"active_rule_catalog",
	"canonical_rule_payload",
	"canonicalize_ruleset",
	"catalog_from_rows",
	"fact_descriptors",
	"fact_metadata",
	"normalize_condition",
	"normalize_feature_scope",
	"normalize_group_catalog",
	"normalize_rule_data",
	"normalize_rule_version_data",
	"normalize_target_actions",
	"ruleset_digest",
	"surface_outcome_mappings",
	"validate_catalog",
]
