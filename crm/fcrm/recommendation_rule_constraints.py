"""Pure validation and preview helpers for CRM Recommendation Rules."""

from __future__ import annotations

import json
from typing import Any

MAX_CONDITIONS_PER_GROUP = 20
TRIGGER_TYPES = frozenset({"event", "state", "inactivity", "deadline", "manual"})
COOLDOWN_UNITS = frozenset({"minutes", "hours", "days"})
PRIORITIES = frozenset({"high", "medium", "low"})
STOP_CONDITIONS = frozenset(
	{
		"matching_action_completed",
		"student_converted",
		"student_lost",
		"student_unsubscribed",
		"owner_changed",
	}
)

CONDITION_FIELDS = {
	"student.lifecycle_stage": {
		"label": "Lifecycle Stage",
		"type": "select",
		"operators": ("equals", "not_equals", "in", "not_in"),
		"options": ("Lead", "MQL", "Applicant", "Enrolled", "Lost"),
	},
	"student.enrollment_status": {
		"label": "Enrollment Status",
		"type": "link",
		"options_doctype": "CRM Enrollment Status",
		"operators": ("equals", "not_equals", "in", "not_in"),
	},
	"student.study_stage": {
		"label": "Study Stage",
		"type": "select",
		"operators": ("equals", "not_equals", "in", "not_in"),
		"options": ("grade_10", "grade_11", "grade_12_h1", "grade_12_h2", "post_exam"),
	},
	"student.current_grade": {
		"label": "Current Grade",
		"type": "select",
		"operators": ("equals", "not_equals", "in", "not_in"),
		"options": ("10", "11", "12", "post_exam"),
	},
	"student.interest_level": {
		"label": "Interest Level",
		"type": "select",
		"operators": ("equals", "not_equals", "in", "not_in"),
		"options": ("High", "Medium", "Low", "Unknown"),
	},
	"student.fit_level": {
		"label": "Fit Level",
		"type": "select",
		"operators": ("equals", "not_equals", "in", "not_in"),
		"options": ("High", "Medium", "Low", "Unknown"),
	},
	"student.primary_barrier": {
		"label": "Primary Barrier",
		"type": "select",
		"operators": ("equals", "not_equals", "in", "not_in"),
		"options": (
			"Cost",
			"Capability",
			"Family",
			"Information",
			"Geography",
			"Competition",
			"None",
			"Unknown",
		),
	},
	"student.latest_score": {
		"label": "Latest Score",
		"type": "number",
		"operators": ("equals", "not_equals", "gt", "gte", "lt", "lte"),
	},
	"student.owner_staff": {
		"label": "Owner Staff",
		"type": "link",
		"options_doctype": "CRM Staff",
		"operators": ("equals", "not_equals", "in", "not_in", "is_empty", "not_empty"),
	},
	"student.owning_team": {
		"label": "Owning Team",
		"type": "link",
		"options_doctype": "CRM Team",
		"operators": ("equals", "not_equals", "in", "not_in", "is_empty", "not_empty"),
	},
	"student.branch": {
		"label": "Campus",
		"type": "link",
		"options_doctype": "CRM Campus",
		"operators": ("equals", "not_equals", "in", "not_in"),
	},
	"student.major": {
		"label": "Major",
		"type": "link",
		"options_doctype": "CRM Major",
		"operators": ("equals", "not_equals", "in", "not_in"),
	},
	"student.source": {
		"label": "Source",
		"type": "link",
		"options_doctype": "CRM Lead Source",
		"operators": ("equals", "not_equals", "in", "not_in"),
	},
}

_NUMERIC_OPERATORS = frozenset({"gt", "gte", "lt", "lte"})
_LIST_OPERATORS = frozenset({"in", "not_in"})
_EMPTY_OPERATORS = frozenset({"is_empty", "not_empty"})
_SCALAR_OPERATORS = frozenset({"equals", "not_equals"})


def parse_json(value: Any, field: str, default: Any):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError) as exc:
			raise ValueError(f"{field} must be valid JSON.") from exc
	return value


def normalize_conditions(value: Any) -> dict[str, list[dict[str, Any]]]:
	conditions = parse_json(value, "conditions", {})
	if not isinstance(conditions, dict):
		raise ValueError("conditions must be a JSON object with 'all' and 'any' lists.")

	normalized = {}
	for group_name in ("all", "any"):
		group = conditions.get(group_name, [])
		if not isinstance(group, list):
			raise ValueError(f"conditions.{group_name} must be a list.")
		if len(group) > MAX_CONDITIONS_PER_GROUP:
			raise ValueError(
				f"conditions.{group_name} cannot contain more than {MAX_CONDITIONS_PER_GROUP} conditions."
			)
		normalized[group_name] = []
		for condition in group:
			_validate_condition(condition)
			normalized[group_name].append(
				{
					"field": condition["field"],
					"operator": condition["operator"],
					**({"value": condition["value"]} if "value" in condition else {}),
				}
			)

	if not normalized["all"] and not normalized["any"]:
		raise ValueError("A Recommendation Rule requires at least one condition.")
	return normalized


def _validate_condition(condition: Any) -> None:
	if not isinstance(condition, dict):
		raise ValueError("Each Recommendation Rule condition must be a JSON object.")
	field = condition.get("field")
	operator = condition.get("operator")
	if field not in CONDITION_FIELDS:
		raise ValueError(f"Field '{field}' is not allowed in Recommendation Rule conditions.")
	if operator not in CONDITION_FIELDS[field]["operators"]:
		raise ValueError(f"Operator '{operator}' is not allowed for field '{field}'.")

	if operator in _EMPTY_OPERATORS:
		return
	if "value" not in condition or condition["value"] in (None, ""):
		raise ValueError(f"Condition on field '{field}' is missing a value.")
	if operator in _LIST_OPERATORS:
		if not isinstance(condition["value"], list) or not condition["value"]:
			raise ValueError(f"Operator '{operator}' requires a non-empty list value for field '{field}'.")
	if operator in _NUMERIC_OPERATORS | _SCALAR_OPERATORS and CONDITION_FIELDS[field]["type"] == "number":
		try:
			float(condition["value"])
		except (TypeError, ValueError) as exc:
			raise ValueError(f"Condition value for '{field}' must be numeric.") from exc


def normalize_stop_conditions(value: Any) -> list[str]:
	conditions = parse_json(value, "stop_conditions", [])
	if not isinstance(conditions, list):
		raise ValueError("stop_conditions must be a JSON array.")
	if any(not isinstance(condition, str) for condition in conditions):
		raise ValueError("stop_conditions must contain only string codes.")
	if len(conditions) != len(set(conditions)):
		raise ValueError("stop_conditions cannot contain duplicates.")
	if any(condition not in STOP_CONDITIONS for condition in conditions):
		raise ValueError(f"stop_conditions must only contain {sorted(STOP_CONDITIONS)}.")
	return conditions


def validate_rule_settings(
	trigger_type: Any,
	trigger_event: Any,
	priority: Any,
	cooldown_value: Any,
	cooldown_unit: Any,
	max_occurrences: Any,
	expires_after_hours: Any,
) -> None:
	if trigger_type not in TRIGGER_TYPES:
		raise ValueError("Recommendation Rule trigger type is invalid.")
	if trigger_type == "event" and not trigger_event:
		raise ValueError("Event Recommendation Rules require trigger_event.")
	if priority not in PRIORITIES:
		raise ValueError("Recommendation Rule priority is invalid.")
	if cooldown_unit not in COOLDOWN_UNITS:
		raise ValueError("Recommendation Rule cooldown unit is invalid.")
	try:
		cooldown = float(cooldown_value or 0)
	except (TypeError, ValueError) as exc:
		raise ValueError("Recommendation Rule cooldown value is invalid.") from exc
	if cooldown < 0:
		raise ValueError("Recommendation Rule cooldown cannot be negative.")
	try:
		occurrences = int(max_occurrences or 0)
	except (TypeError, ValueError) as exc:
		raise ValueError("Recommendation Rule max occurrences is invalid.") from exc
	if occurrences < 1:
		raise ValueError("Recommendation Rule max occurrences must be at least one.")
	if expires_after_hours not in (None, ""):
		try:
			expires = float(expires_after_hours)
		except (TypeError, ValueError) as exc:
			raise ValueError("Recommendation Rule expiry value is invalid.") from exc
		if expires < 0:
			raise ValueError("Recommendation Rule expiry cannot be negative.")


def condition_metadata() -> list[dict[str, Any]]:
	return [
		{
			"field": field,
			**{key: list(value) if isinstance(value, tuple) else value for key, value in metadata.items()},
		}
		for field, metadata in CONDITION_FIELDS.items()
	]


def _context_value(context: dict[str, Any], field: str):
	if field in context:
		return context[field]
	short_field = field.removeprefix("student.")
	student = context.get("student")
	if isinstance(student, dict) and short_field in student:
		return student[short_field]
	return context.get(short_field)


def _compare(left: Any, right: Any, operator: str) -> bool:
	if operator in _EMPTY_OPERATORS:
		is_empty = left in (None, "", [])
		return is_empty if operator == "is_empty" else not is_empty
	if left in (None, "", []):
		return False
	if operator in _LIST_OPERATORS:
		result = left in right if isinstance(right, list) else False
		return result if operator == "in" else not result
	if operator in _NUMERIC_OPERATORS:
		try:
			left_number = float(left)
			right_number = float(right)
		except (TypeError, ValueError):
			return False
		return {
			"gt": left_number > right_number,
			"gte": left_number >= right_number,
			"lt": left_number < right_number,
			"lte": left_number <= right_number,
		}[operator]
	if operator == "equals":
		return left == right
	if operator == "not_equals":
		return left != right
	return False


def _matches(condition: dict[str, Any], context: dict[str, Any]) -> bool:
	return _compare(
		_context_value(context, condition["field"]),
		condition.get("value"),
		condition["operator"],
	)


def evaluate_conditions(value: Any, context: dict[str, Any]) -> bool:
	conditions = normalize_conditions(value)
	all_matches = all(_matches(condition, context) for condition in conditions["all"])
	any_matches = not conditions["any"] or any(
		_matches(condition, context) for condition in conditions["any"]
	)
	return all_matches and any_matches
