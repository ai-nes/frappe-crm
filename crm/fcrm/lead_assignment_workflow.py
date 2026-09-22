"""Governed configuration for the Lead assignment workflow.

The workflow graph is intentionally fixed in v1.  This module owns the small
set of operational settings that may be changed by a Lead Sale while keeping
the safety steps and their input/output contract immutable.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import frappe
from frappe import _

WORKFLOW_SCHEMA_VERSION = "lead-assignment-workflow-v1"
CONTROL_DOCTYPE = "CRM Assignment Control"
MAX_SCHEDULED_AGE_MINUTES = 24 * 60
MAX_LEADS_PER_RUN = 1000
MAX_RETRIES = 10

STEP_IDS = ("input", "validation", "classification", "matching", "review", "assignment")
TOGGLEABLE_STEP_IDS = frozenset(("input", "classification"))
LOCKED_STEP_IDS = frozenset(set(STEP_IDS) - TOGGLEABLE_STEP_IDS)
IMMUTABLE_STEP_IDS = frozenset(("validation", "matching", "assignment"))

_DEFAULT_STORED_CONFIG = {
	"input": {
		"enabled": True,
		"scheduledMinAgeMinutes": 5,
		"maxLeadsPerRun": MAX_LEADS_PER_RUN,
	},
	"classification": {
		"enabled": True,
	},
	"review": {
		"maxRetries": 3,
	},
}


def _as_bool(value: Any, default: bool = False) -> bool:
	if value is None:
		return default
	if isinstance(value, bool):
		return value
	if isinstance(value, str):
		return value.strip().lower() in {"1", "true", "yes", "on"}
	return bool(value)


def _as_int(value: Any, default: int, minimum: int, maximum: int) -> int:
	try:
		value = int(value)
	except (TypeError, ValueError):
		return default
	return max(minimum, min(value, maximum))


def _json_object(value: Any) -> dict[str, Any]:
	if isinstance(value, dict):
		return value
	if isinstance(value, str) and value.strip():
		try:
			parsed = json.loads(value)
		except (TypeError, ValueError):
			return {}
		return parsed if isinstance(parsed, dict) else {}
	return {}


def _stored_config(value: Any = None) -> dict[str, Any]:
	config = copy.deepcopy(_DEFAULT_STORED_CONFIG)
	value = _json_object(value)

	input_values = value.get("input") if isinstance(value.get("input"), dict) else {}
	config["input"].update(
		{
			"enabled": _as_bool(input_values.get("enabled"), True),
			"scheduledMinAgeMinutes": _as_int(
				input_values.get("scheduledMinAgeMinutes"), 5, 0, MAX_SCHEDULED_AGE_MINUTES
			),
			"maxLeadsPerRun": _as_int(
				input_values.get("maxLeadsPerRun"), MAX_LEADS_PER_RUN, 1, MAX_LEADS_PER_RUN
			),
		}
	)

	classification_values = (
		value.get("classification") if isinstance(value.get("classification"), dict) else {}
	)
	config["classification"].update(
		{"enabled": _as_bool(classification_values.get("enabled"), True)}
	)

	review_values = value.get("review") if isinstance(value.get("review"), dict) else {}
	config["review"].update(
		{"maxRetries": _as_int(review_values.get("maxRetries"), 3, 0, MAX_RETRIES)}
	)
	return config


def _control_values() -> dict[str, Any]:
	if not frappe.db.exists("DocType", CONTROL_DOCTYPE):
		return {}
	try:
		doc = frappe.get_single(CONTROL_DOCTYPE)
		return {
			"lead_assignment_workflow_config": doc.get("lead_assignment_workflow_config"),
			"lead_workflow_revision": doc.get("lead_workflow_revision"),
			"lead_workflow_last_changed_by": doc.get("lead_workflow_last_changed_by"),
			"lead_workflow_last_change_reason": doc.get("lead_workflow_last_change_reason"),
		}
	except Exception:
		return {}


def _revision(control: dict[str, Any]) -> int:
	try:
		return max(0, int(control.get("lead_workflow_revision") or 0))
	except (TypeError, ValueError):
		return 0


def get_lead_assignment_workflow_config(control: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Return the effective v1 workflow configuration with safe defaults."""
	control = control or _control_values()
	stored = _stored_config(control.get("lead_assignment_workflow_config"))
	revision = _revision(control)
	return {
		"schemaVersion": WORKFLOW_SCHEMA_VERSION,
		"version": f"lead-assignment-workflow-v{revision}",
		"revision": revision,
		"applyScope": "new_decisions",
		"lastChangedBy": control.get("lead_workflow_last_changed_by"),
		"lastChangeReason": control.get("lead_workflow_last_change_reason"),
		"stored": stored,
	}


def normalize_step_id(step_id: Any) -> str:
	step_id = str(step_id or "").strip()
	if step_id not in STEP_IDS:
		frappe.throw(_("Bước workflow không được hỗ trợ."), frappe.ValidationError)
	return step_id


def validate_step_update(step_id: Any, settings: Any) -> dict[str, Any]:
	"""Validate and normalize the mutable settings for one workflow step."""
	step_id = normalize_step_id(step_id)
	settings = _json_object(settings)
	if step_id in IMMUTABLE_STEP_IDS:
		if settings:
			frappe.throw(
				_("Bước {0} không cho thay đổi tham số trong phiên bản này.").format(step_id),
				frappe.ValidationError,
			)
		return {}

	if step_id == "input":
		return {
			"enabled": _as_bool(settings.get("enabled"), True),
			"scheduledMinAgeMinutes": _as_int(
				settings.get("scheduledMinAgeMinutes"), 5, 0, MAX_SCHEDULED_AGE_MINUTES
			),
			"maxLeadsPerRun": _as_int(
				settings.get("maxLeadsPerRun"), MAX_LEADS_PER_RUN, 1, MAX_LEADS_PER_RUN
			),
		}

	if step_id == "classification":
		return {"enabled": _as_bool(settings.get("enabled"), True)}

	return {
		"maxRetries": _as_int(settings.get("maxRetries"), 3, 0, MAX_RETRIES),
	}


def update_stored_step(
	control: dict[str, Any], step_id: Any, settings: Any
) -> dict[str, Any]:
	"""Return a new normalized stored config after updating one mutable step."""
	step_id = normalize_step_id(step_id)
	values = validate_step_update(step_id, settings)
	stored = _stored_config(control.get("lead_assignment_workflow_config"))
	if step_id in TOGGLEABLE_STEP_IDS:
		stored[step_id] = values
	elif step_id == "review":
		stored[step_id] = values
	return stored


def step_snapshot(config: dict[str, Any], step_id: str, policy: dict[str, Any] | None = None) -> dict[str, Any]:
	"""Build the UI-facing snapshot for a fixed workflow node."""
	step_id = normalize_step_id(step_id)
	stored = config["stored"]
	if step_id == "input":
		settings = stored["input"]
	elif step_id == "classification":
		settings = stored["classification"]
	elif step_id == "review":
		settings = {
			"retryMode": "manual",
			**stored["review"],
		}
	elif step_id == "validation":
		settings = {
			"requiredFields": ["student_name", "phone", "province"],
			"optionalFields": ["high_school", "major"],
			"invalidOutcome": "review",
		}
	elif step_id == "matching":
		settings = {
			"routingPolicy": policy or {},
			"noEligibleOutcome": "review",
		}
	else:
		settings = {
			"preserveExistingOwner": True,
			"recipientFunctions": ["Sale", "CTV Sale"],
			"createStudent": False,
		}
	return {
		"id": step_id,
		"enabled": True if step_id in LOCKED_STEP_IDS else bool(settings.get("enabled", True)),
		"canToggle": step_id in TOGGLEABLE_STEP_IDS,
		"settings": settings,
	}
