"""PII-safe rule decision and trace projections at the Frappe boundary.

The agent service performs the same projection before transport, but Frappe
must validate the untrusted service payload again before persistence.  This
module deliberately accepts metadata only: raw facts, messages, CRM
identifiers and arbitrary model text are not part of the stored contract.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from crm.fcrm.rule_engine import ACTION_CODES, OUTCOMES, VERSION_ID_PATTERN

_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REASON = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_TRACE_KIND = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)")
_ISO_DATE_OR_TIMESTAMP = re.compile(
	r"^\d{4}-\d{2}-\d{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?$"
)

RULE_DECISION_FIELDS = frozenset(
	{
		"outcome",
		"matched_rule_ids",
		"reason_codes",
		"business_reason",
		"sales_next_step",
		"affected_actions",
		"rule_version",
		"rule_version_digest",
		"ruleset_digest",
	}
)

# Trace entries are an audit projection, not a copy of the NBA evaluator
# output.  The allowlist is intentionally small and recursive so adding a
# field to the model trace cannot silently expand what Frappe stores.
TRACE_ENTRY_FIELDS = frozenset(
	{
		"kind", "value", "action_id", "reason", "rank", "matched_opportunities",
		"score", "effectiveness_index", "confidence", "timing_status", "selected",
		"decided_by", "addresses_needs", "desired_outcomes", "collects_information",
		"readiness_target", "matched_needs", "premises_used", "missing_facets",
		"unscoped_action", "coverage",
	}
)
TRACE_VALUE_FIELDS = frozenset(
	{
		"outcome",
		"matched_rule_ids",
		"reason_codes",
		"business_reason",
		"sales_next_step",
		"affected_actions",
		"rule_version",
		"rule_version_digest",
		"ruleset_digest",
		"version_id",
		"version_name",
		"ruleset_revision",
		"feature_scope",
		"disposition",
		"status",
		"reason_code",
		"trace_ref",
		"feedback_code",
		"action_id",
		"action_ids",
		"rank",
		"selected",
		"decided_by",
		"schema_revision",
		"code",
		"urgency",
		"evidence_refs",
		"premises",
		"supporting_signal_ids",
		"supporting_evidence_refs",
		"need_code",
		"basis",
		"blocks_progress",
		"explicit_request",
		"advice_readiness",
		"application_readiness",
		"parent_influence",
		"target_transition",
		"primary_need",
		"primary_blocker",
		"hypotheses",
		"clarification_needed",
		"rubric_revision",
		"progress_blocker",
		"need_assessment",
		"student_stage",
		"student_stage_known",
		"student_stage_present",
		"intent_type",
		"intent_polarity",
		"engagement_state",
		"last_contact_days",
		"application_completeness",
		"missing_requirement_count",
		"academic_gpa",
		"academic_quality",
		"missing_requirements",
		"blockers",
		"nearest_deadline_at",
		"days_to_deadline",
		"contact_consent",
		"contact_channels",
		"parent_authority_valid",
		"work_in_flight",
		"interest_disposition",
		"application_assessment",
		"follow_up_state",
		"follow_up_revisit_at",
		"contact_consecutive_failures",
		"decision_status",
		"enrollment_assessment",
		"parent_disposition",
		"freshness",
		"missingness",
		"conflicts",
		"markers",
		"effect_coverage_incomplete",
		"components",
		"penalties",
		"total",
		"effectiveness_index",
		"timing_status",
		"matched_opportunities",
		"premises_used",
		"missing_facets",
		"unscoped_action",
		"coverage",
	})
_FORBIDDEN_KEYS = frozenset(
	{
		"content",
		"raw_content",
		"transcript",
		"quoted_text",
		"message",
		"email",
		"phone",
		"mobile",
		"student",
		"student_id",
		"parent",
		"parent_id",
		"contact",
		"contact_id",
		"name",
		"full_name",
	}
)
MAX_TRACE_ENTRIES = 64
MAX_TRACE_BYTES = 50_000
MAX_TRACE_DEPTH = 4
MAX_TRACE_LIST = 32
MAX_TRACE_OBJECT_FIELDS = 64
MAX_TRACE_STRING = 800
_REFERENCE_VALUE_FIELDS = frozenset(
	{
		"trace_ref",
		"evidence_refs",
		"supporting_signal_ids",
		"supporting_evidence_refs",
		"action_id",
		"action_ids",
	}
)


def _parse_json(value: Any, label: str) -> Any:
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError) as exc:
			raise ValueError(f"{label} must be valid JSON") from exc
	return value


def _text(
	value: Any,
	label: str,
	*,
	maximum: int = MAX_TRACE_STRING,
	reject_pii: bool = True,
) -> str:
	if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
		raise ValueError(f"{label} must be a bounded string")
	text = value.strip()
	if any(ord(char) < 32 for char in text):
		raise ValueError(f"{label} contains a control character")
	if reject_pii and (
		_EMAIL.search(text) or (_PHONE.search(text) and not _ISO_DATE_OR_TIMESTAMP.fullmatch(text))
	):
		raise ValueError(f"{label} contains a PII-shaped value")
	return text


def validate_rule_decision(value: Any) -> dict[str, Any]:
	"""Validate and normalize one mandatory rule decision projection."""
	value = _parse_json(value, "rule_decision")
	legacy_fields = RULE_DECISION_FIELDS - {"sales_next_step"}
	if not isinstance(value, Mapping):
		raise ValueError("rule_decision contains unsupported or missing fields")
	if set(value) == legacy_fields:
		value = dict(value)
		value["sales_next_step"] = "Chưa có bước tiếp theo được xác định."
	if set(value) != RULE_DECISION_FIELDS:
		raise ValueError("rule_decision contains unsupported or missing fields")
	outcome = value.get("outcome")
	if outcome not in OUTCOMES:
		raise ValueError("rule_decision outcome is invalid")
	matched = value.get("matched_rule_ids")
	reasons = value.get("reason_codes")
	actions = value.get("affected_actions")
	if not isinstance(matched, list) or len(matched) > 50 or any(
		not isinstance(item, str) or not _ID.fullmatch(item) for item in matched
	):
		raise ValueError("rule_decision matched_rule_ids is invalid")
	if len(set(matched)) != len(matched):
		raise ValueError("rule_decision matched_rule_ids must be unique")
	if not isinstance(reasons, list) or not 1 <= len(reasons) <= 12 or any(
		not isinstance(item, str) or not _REASON.fullmatch(item) for item in reasons
	):
		raise ValueError("rule_decision reason_codes is invalid")
	if reasons != sorted(set(reasons)):
		raise ValueError("rule_decision reason_codes must be sorted and unique")
	if not isinstance(actions, list) or len(actions) > 30 or any(
		not isinstance(item, str) or item not in ACTION_CODES for item in actions
	):
		raise ValueError("rule_decision affected_actions is invalid")
	if len(set(actions)) != len(actions):
		raise ValueError("rule_decision affected_actions must be unique")
	# Rule-version identifiers are control-plane metadata, not free-form model
	# text.  Do not run the generic phone-shaped PII detector over them: valid
	# version IDs may legitimately contain a long numeric revision or timestamp
	# (for example ``TEST-NBA-2026091101``).  The canonical control-plane
	# pattern still keeps the identifier bounded and non-ambiguous.
	rule_version = _text(
		value.get("rule_version"),
		"rule_decision.rule_version",
		maximum=140,
		reject_pii=False,
	)
	if not VERSION_ID_PATTERN.fullmatch(rule_version):
		raise ValueError("rule_decision.rule_version is invalid")
	for fieldname in ("rule_version_digest", "ruleset_digest"):
		if not isinstance(value.get(fieldname), str) or not _HEX64.fullmatch(value[fieldname]):
			raise ValueError(f"rule_decision {fieldname} is invalid")
	if value["rule_version_digest"] != value["ruleset_digest"]:
		raise ValueError("rule_decision identity digests must agree")
	return {
		"outcome": outcome,
		"matched_rule_ids": list(matched),
		"reason_codes": list(reasons),
		"business_reason": _text(value.get("business_reason"), "rule_decision.business_reason"),
		"sales_next_step": _text(value.get("sales_next_step"), "rule_decision.sales_next_step"),
		"affected_actions": list(actions),
		"rule_version": rule_version,
		"rule_version_digest": value["rule_version_digest"],
		"ruleset_digest": value["ruleset_digest"],
	}


def _validate_trace_value(value: Any, *, depth: int, label: str) -> Any:
	if depth > MAX_TRACE_DEPTH:
		raise ValueError("trace nesting exceeds the maximum depth")
	if value is None or isinstance(value, (bool, int)):
		return value
	if isinstance(value, float):
		if value != value or value in (float("inf"), float("-inf")):
			raise ValueError("trace contains a non-finite number")
		return value
	if isinstance(value, str):
		return _text(value, label)
	if isinstance(value, list):
		if len(value) > MAX_TRACE_LIST:
			raise ValueError("trace list exceeds the maximum length")
		return [_validate_trace_value(item, depth=depth + 1, label=label) for item in value]
	if isinstance(value, Mapping):
		if len(value) > MAX_TRACE_OBJECT_FIELDS:
			raise ValueError("trace object exceeds the maximum field count")
		result = {}
		for key, item in value.items():
			if not isinstance(key, str) or key in _FORBIDDEN_KEYS or key not in TRACE_VALUE_FIELDS:
				raise ValueError("trace contains an unsupported or sensitive field")
			if key in _REFERENCE_VALUE_FIELDS:
				if isinstance(item, list):
					if len(item) > MAX_TRACE_LIST:
						raise ValueError("trace reference list exceeds the maximum length")
					result[key] = [
						_text(
							child,
							f"{label}.{key}[]",
							reject_pii=False,
						)
						for child in item
					]
				else:
					result[key] = _text(item, f"{label}.{key}", reject_pii=False)
			elif key in {"components", "penalties", "markers"}:
				if not isinstance(item, Mapping) or len(item) > 32:
					raise ValueError("trace metric map is invalid")
				result[key] = {}
				for metric, metric_value in item.items():
					if (
						not isinstance(metric, str)
						or metric in _FORBIDDEN_KEYS
						or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", metric)
					):
						raise ValueError("trace metric key is invalid")
					result[key][metric] = _validate_trace_value(
						metric_value, depth=depth + 1, label=f"{label}.{key}.{metric}"
					)
			else:
				result[key] = _validate_trace_value(item, depth=depth + 1, label=f"{label}.{key}")
		return result
	raise ValueError("trace contains an unsupported value type")


def validate_trace_entries(value: Any) -> list[dict[str, Any]]:
	"""Validate the bounded, PII-safe trace entry projection."""
	value = _parse_json(value, "trace_entries")
	if value in (None, ""):
		return []
	if not isinstance(value, list) or len(value) > MAX_TRACE_ENTRIES:
		raise ValueError("trace_entries must be a bounded array")
	entries = []
	for index, entry in enumerate(value):
		if not isinstance(entry, Mapping) or set(entry) - TRACE_ENTRY_FIELDS or "kind" not in entry:
			raise ValueError("trace entry contains unsupported fields")
		kind = entry["kind"]
		if not isinstance(kind, str) or not _TRACE_KIND.fullmatch(kind):
			raise ValueError("trace entry kind is invalid")
		item = {"kind": kind}
		for fieldname, fieldvalue in entry.items():
			if fieldname == "kind":
				continue
			if fieldname in {"action_id", "reason", "timing_status", "decided_by"}:
				if fieldname == "action_id" and fieldvalue is None:
					item[fieldname] = None
				else:
					item[fieldname] = _text(fieldvalue, f"trace_entries[{index}].{fieldname}", maximum=140)
			elif fieldname == "rank":
				if fieldvalue is None:
					item[fieldname] = None
					continue
				if isinstance(fieldvalue, bool) or not isinstance(fieldvalue, int) or not 1 <= fieldvalue <= 50:
					raise ValueError("trace entry rank is invalid")
				item[fieldname] = fieldvalue
			elif fieldname in {"selected", "collects_information", "unscoped_action"}:
				if not isinstance(fieldvalue, bool):
					raise ValueError("trace entry boolean is invalid")
				item[fieldname] = fieldvalue
			elif fieldname in {"effectiveness_index", "confidence"}:
				if not isinstance(fieldvalue, (int, float)) or isinstance(fieldvalue, bool) or not 0 <= fieldvalue <= 1:
					raise ValueError("trace entry score is invalid")
				item[fieldname] = fieldvalue
			elif fieldname == "readiness_target":
				item[fieldname] = _text(fieldvalue, f"trace_entries[{index}].{fieldname}", maximum=140)
			elif fieldname in {
				"matched_opportunities", "addresses_needs", "desired_outcomes",
				"matched_needs", "premises_used", "missing_facets",
			}:
				if not isinstance(fieldvalue, list) or len(fieldvalue) > MAX_TRACE_LIST:
					raise ValueError("trace entry list is invalid")
				item[fieldname] = [
					_text(child, f"trace_entries[{index}].{fieldname}[]", maximum=140)
					for child in fieldvalue
				]
			elif fieldname in {"value", "score"}:
				safe_value = fieldvalue
				# The evaluator's state trace contains detailed provenance. It is
				# useful locally but must not cross the Frappe persistence boundary.
				if fieldname == "value" and kind == "state" and isinstance(safe_value, Mapping):
					safe_value = {
						key: child for key, child in safe_value.items() if key != "effect_provenance"
					}
				item[fieldname] = _validate_trace_value(
					safe_value, depth=0, label=f"trace_entries[{index}].{fieldname}"
				)
		entries.append(item)
	encoded = json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
	if len(encoded.encode("utf-8")) > MAX_TRACE_BYTES:
		raise ValueError("trace_entries exceeds the maximum size")
	return entries


def validate_trace_projection(value: Any) -> dict[str, Any]:
	"""Validate a stored object containing only one rule decision."""
	value = _parse_json(value, "trace_projection")
	if not isinstance(value, Mapping) or set(value) != {"rule_decision"}:
		raise ValueError("trace_projection contains unsupported fields")
	return {"rule_decision": validate_rule_decision(value["rule_decision"])}


__all__ = ["validate_rule_decision", "validate_trace_entries", "validate_trace_projection"]
