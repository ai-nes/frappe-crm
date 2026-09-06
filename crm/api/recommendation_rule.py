"""Admin APIs for configuring and previewing Recommendation Rules."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import frappe
from frappe import _

from crm.api._pagination import paged_list
from crm.fcrm.nba_timing import is_time_allowed, resolve_scheduled_at
from crm.fcrm.recommendation_rule_constraints import (
	condition_metadata,
	evaluate_conditions,
	normalize_conditions,
	normalize_stop_conditions,
	validate_rule_settings,
)

RULE_LIST_FIELDS = [
	"name",
	"rule_key",
	"display_name",
	"status",
	"enabled",
	"version",
	"action",
	"priority",
	"trigger_type",
	"trigger_event",
	"description",
	"conditions",
	"timing_policy",
	"cooldown_value",
	"cooldown_unit",
	"max_occurrences",
	"expires_after_hours",
	"stop_conditions",
	"published_at",
	"published_by",
	"archive_reason",
	"modified",
]

WRITABLE_FIELDS = {
	"display_name",
	"description",
	"action",
	"priority",
	"trigger_type",
	"trigger_event",
	"conditions",
	"timing_policy",
	"cooldown_value",
	"cooldown_unit",
	"max_occurrences",
	"expires_after_hours",
	"stop_conditions",
}


def _parse_payload(value: Any, field: str, default: Any):
	if value in (None, ""):
		return default
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			frappe.throw(_("{0} must be valid JSON.").format(field), frappe.ValidationError)
	return value


def _normalise_values(values: dict[str, Any]) -> dict[str, Any]:
	values = dict(values)
	if "action_code" in values:
		if "action" in values and values["action"] != values["action_code"]:
			frappe.throw(_("action and action_code must refer to the same Action."), frappe.ValidationError)
		values["action"] = values.pop("action_code")
	for field, normalizer, default in (
		("conditions", normalize_conditions, {}),
		("stop_conditions", normalize_stop_conditions, []),
	):
		if field in values:
			try:
				values[field] = json.dumps(
					normalizer(_parse_payload(values[field], field, default)), ensure_ascii=False
				)
			except ValueError as exc:
				frappe.throw(str(exc), frappe.ValidationError)
	return values


def _api_payload(doc) -> dict[str, Any]:
	as_dict = getattr(doc, "as_dict", None)
	payload = as_dict() if callable(as_dict) else dict(doc)
	payload["action_code"] = payload.get("action")
	for field, normalizer, default in (
		("conditions", normalize_conditions, {}),
		("stop_conditions", normalize_stop_conditions, []),
	):
		try:
			payload[field] = normalizer(payload.get(field) or default)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)
	return payload


def _set_writable_fields(doc, values: dict[str, Any]) -> None:
	for fieldname in WRITABLE_FIELDS:
		if fieldname in values:
			doc.set(fieldname, values[fieldname])


def _get_rule(name: str, permission_type: str = "read"):
	doc = frappe.get_doc("CRM Recommendation Rule", name)
	doc.check_permission(permission_type)
	return doc


def _validate_action_for_publish(action_name: str):
	if not action_name:
		frappe.throw(_("A Recommendation Rule requires an Action."), frappe.ValidationError)
	action = frappe.get_doc("CRM Action", action_name)
	action.check_permission("read")
	if not action.enabled:
		frappe.throw(
			_("The selected Action is disabled and cannot be published."),
			frappe.ValidationError,
			title="ACTION_DISABLED",
		)
	return action


def _student_context(context: dict[str, Any]) -> dict[str, Any]:
	context = dict(context)
	student = context.get("student")
	if isinstance(student, str):
		student_doc = frappe.get_doc("CRM Student", student)
		student_doc.check_permission("read")
		context["student"] = student_doc.as_dict()
	return context


def _datetime_text(value: Any) -> str | None:
	return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


@frappe.whitelist()
def list_rules(
	status: str | None = None,
	enabled: str | int | None = None,
	action_code: str | None = None,
	trigger_type: str | None = None,
	search: str | None = None,
	start: int = 0,
	page_length: int = 20,
):
	filters = {}
	if status:
		filters["status"] = status
	if enabled not in (None, ""):
		filters["enabled"] = frappe.utils.cint(enabled)
	if action_code:
		filters["action"] = action_code
	if trigger_type:
		filters["trigger_type"] = trigger_type

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [
			["rule_key", "like", like],
			["display_name", "like", like],
			["description", "like", like],
		]

	result = paged_list(
		"CRM Recommendation Rule",
		RULE_LIST_FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="modified desc",
	)
	rows = [_api_payload(row) for row in result.pop("rows")]
	return {**result, "rules": rows}


@frappe.whitelist()
def get_rule(name: str):
	return _api_payload(_get_rule(name))


@frappe.whitelist(methods=["POST"])
def create_rule(**values):
	values = _normalise_values(values)
	# A rule without an event is an intentional manual rule. The DocType's
	# historical default is ``event`` for persisted records, so make the API
	# default explicit before inserting rather than asking non-technical users
	# to provide an event they did not configure.
	if "trigger_type" not in values and not values.get("trigger_event"):
		values["trigger_type"] = "manual"
	rule_key = values.pop("rule_key", None) or values.pop("key", None)
	values.pop("status", None)
	values.pop("version", None)
	values.pop("enabled", None)
	values["status"] = "draft"
	values["enabled"] = 0
	values.setdefault("stop_conditions", json.dumps([], ensure_ascii=False))
	doc = frappe.new_doc("CRM Recommendation Rule")
	doc.rule_key = rule_key
	_set_writable_fields(doc, values)
	if not doc.rule_key:
		frappe.throw(_("rule_key is required."), frappe.ValidationError)
	doc.insert()
	return _api_payload(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_rule(name: str, **values):
	doc = _get_rule(name, "write")
	if "rule_key" in values and values["rule_key"] != doc.rule_key:
		frappe.throw(_("Recommendation Rule key cannot be changed after creation."), frappe.ValidationError)
	values.pop("rule_key", None)
	values.pop("status", None)
	values.pop("version", None)
	values.pop("enabled", None)
	values = _normalise_values(values)
	lifecycle_transition = doc.status in {"published", "archived"}
	if doc.status in {"published", "archived"}:
		doc.status = "draft"
		doc.enabled = 0
		doc.archive_reason = None
	_set_writable_fields(doc, values)
	previous = getattr(frappe.flags, "recommendation_rule_lifecycle", False)
	frappe.flags.recommendation_rule_lifecycle = lifecycle_transition
	try:
		doc.save()
	finally:
		frappe.flags.recommendation_rule_lifecycle = previous
	return _api_payload(doc)


def _lock_rule(name: str):
	rows = frappe.db.sql(
		"SELECT name FROM `tabCRM Recommendation Rule` WHERE name = %s FOR UPDATE",
		(name,),
		as_dict=True,
	)
	if not rows:
		frappe.throw(_("Recommendation Rule {0} does not exist.").format(name), frappe.DoesNotExistError)
	return _get_rule(name, "write")


@frappe.whitelist(methods=["POST"])
def publish_rule(name: str, expected_version: int | str | None = None):
	doc = _lock_rule(name)
	if expected_version in (None, ""):
		frappe.throw(
			_("expected_version is required when publishing a Recommendation Rule."),
			frappe.ValidationError,
			title="STALE_RULE_VERSION",
		)
	try:
		expected_version = int(expected_version)
	except (TypeError, ValueError):
		frappe.throw(_("expected_version must be an integer."), frappe.ValidationError)
	if doc.status == "archived":
		frappe.throw(
			_("Archived Recommendation Rules must be edited before they can be published again."),
			frappe.ValidationError,
		)
	if expected_version != int(doc.version or 1):
		frappe.throw(
			_("Recommendation Rule has changed. Reload it before publishing."),
			frappe.ValidationError,
			title="STALE_RULE_VERSION",
		)
	_validate_action_for_publish(doc.action)
	previous = getattr(frappe.flags, "recommendation_rule_publish", False)
	previous_lifecycle = getattr(frappe.flags, "recommendation_rule_lifecycle", False)
	frappe.flags.recommendation_rule_publish = True
	frappe.flags.recommendation_rule_lifecycle = True
	try:
		doc.status = "published"
		doc.enabled = 1
		doc.version = int(doc.version or 1) + 1
		doc.published_at = frappe.utils.now_datetime()
		doc.published_by = frappe.session.user
		doc.save()
	finally:
		frappe.flags.recommendation_rule_publish = previous
		frappe.flags.recommendation_rule_lifecycle = previous_lifecycle
	return _api_payload(doc)


@frappe.whitelist(methods=["POST"])
def archive_rule(name: str, reason: str | None = None):
	doc = _get_rule(name, "write")
	previous = getattr(frappe.flags, "recommendation_rule_archive", False)
	previous_lifecycle = getattr(frappe.flags, "recommendation_rule_lifecycle", False)
	frappe.flags.recommendation_rule_archive = True
	frappe.flags.recommendation_rule_lifecycle = True
	try:
		doc.status = "archived"
		doc.enabled = 0
		doc.archive_reason = reason
		doc.save()
	finally:
		frappe.flags.recommendation_rule_archive = previous
		frappe.flags.recommendation_rule_lifecycle = previous_lifecycle
	return _api_payload(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_rule(name: str):
	"""Permanently delete a draft Recommendation Rule.

	Published and archived Rules are retained for auditability and must be
	archived or edited through the lifecycle APIs instead.
	"""
	doc = _get_rule(name, "delete")
	if doc.status != "draft":
		frappe.throw(
			_("Only draft Recommendation Rules can be deleted. Archive published Rules instead."),
			frappe.PermissionError,
		)
	doc.delete()
	return {"deleted": name}


@frappe.whitelist()
def list_condition_fields():
	return {"fields": condition_metadata()}


@frappe.whitelist(methods=["POST"])
def preview_rule(rule=None, context=None):
	rule_values = _parse_payload(rule, "rule", {})
	context_values = _parse_payload(context, "context", {})
	if not isinstance(rule_values, dict):
		frappe.throw(_("rule must be a JSON object."), frappe.ValidationError)
	if not isinstance(context_values, dict):
		frappe.throw(_("context must be a JSON object."), frappe.ValidationError)
	rule_values = _normalise_values(rule_values)
	trigger_type = rule_values.get("trigger_type") or (
		"manual" if not rule_values.get("trigger_event") else "event"
	)
	try:
		validate_rule_settings(
			trigger_type,
			rule_values.get("trigger_event"),
			rule_values.get("priority") or "medium",
			rule_values.get("cooldown_value") or 0,
			rule_values.get("cooldown_unit") or "days",
			rule_values.get("max_occurrences") or 1,
			rule_values.get("expires_after_hours"),
		)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
	try:
		conditions = normalize_conditions(rule_values.get("conditions"))
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
	if not rule_values.get("action"):
		frappe.throw(_("A preview requires action_code."), frappe.ValidationError)
	action = frappe.get_doc("CRM Action", rule_values["action"])
	action.check_permission("read")
	context_values = _student_context(context_values)
	timing_valid = True
	action_time_allowed = True
	warnings = []
	if not action.enabled:
		warnings.append({"code": "ACTION_DISABLED", "message": "Action is disabled."})
	if action.execution_type == "AI_ASSISTED" and not action.ai_allowed:
		warnings.append(
			{"code": "ACTION_AI_NOT_ALLOWED", "message": "AI-assisted Action does not allow AI execution."}
		)

	now = frappe.utils.now_datetime()
	next_at = now
	expires_at = None
	policy_name = rule_values.get("timing_policy")
	if policy_name:
		policy = frappe.get_doc("CRM Timing Policy", policy_name)
		policy.check_permission("read")
		try:
			next_at = resolve_scheduled_at(policy.as_dict(), now=now)
		except ValueError as exc:
			timing_valid = False
			warnings.append({"code": "TIMING_POLICY_INVALID", "message": str(exc)})
	try:
		if action.allowed_time_slots:
			action_time_allowed = is_time_allowed(next_at, action.allowed_time_slots)
			if not action_time_allowed:
				warnings.append(
					{"code": "ACTION_TIME_WINDOW", "message": "Action is outside its allowed time window."}
				)
	except ValueError as exc:
		action_time_allowed = False
		warnings.append({"code": "ACTION_TIME_WINDOW_INVALID", "message": str(exc)})
	eligible = (
		bool(action.enabled)
		and timing_valid
		and action_time_allowed
		and evaluate_conditions(conditions, context_values)
	)
	if rule_values.get("expires_after_hours") not in (None, ""):
		expires_at = next_at + timedelta(hours=float(rule_values["expires_after_hours"]))
	if not eligible:
		if not action.enabled:
			reason_code, reason = "ACTION_DISABLED", "Action is disabled."
		elif not timing_valid:
			reason_code, reason = "TIMING_POLICY_INVALID", "Timing policy is invalid."
		elif not action_time_allowed:
			reason_code, reason = "ACTION_TIME_WINDOW", "Action is outside its allowed time window."
		else:
			reason_code, reason = (
				"CONDITIONS_NOT_MET",
				"Conditions are not satisfied by the supplied context.",
			)
	else:
		reason_code = None
		reason = None
	return {
		"eligible": eligible,
		"reason_code": reason_code,
		"reason": reason,
		"action": {
			"code": action.code,
			"display_name": action.display_name,
			"channel": action.default_channel,
			"execution_type": action.execution_type,
			"available": bool(action.enabled),
		},
		"timing": {
			"policy": policy_name,
			"next_at": _datetime_text(next_at),
			"expires_at": _datetime_text(expires_at),
		},
		"priority": rule_values.get("priority") or "medium",
		"warnings": warnings,
	}
