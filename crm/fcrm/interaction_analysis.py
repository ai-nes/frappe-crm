"""Frappe-owned settlement command for Interaction analysis results."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from typing import Any

import frappe

from crm.fcrm.decision_trace import validate_rule_decision
from crm.fcrm.intelligence_runs import (
	RULE_IDENTITY_FIELDS,
	_assert_run_ruleset_identity,
	_assert_stage_ruleset_identity,
	_run_ruleset_identity,
)

_STATES = {"no_intent", "intent_bearing", "unknown", "failed"}
_LEASE_SECONDS = 120
_PII_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PII_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)")
_ISO_DATE_OR_TIMESTAMP = re.compile(
	r"\d{4}-\d{2}-\d{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?)?"
)


def _canonical_digest(value: object) -> str:
	return hashlib.sha256(
		json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
	).hexdigest()


def _service_only() -> None:
	service_user = frappe.conf.get("crm_agents_service_user")
	if not service_user or frappe.session.user != service_user:
		frappe.throw("This command is restricted to the CRM-Agents capability.", frappe.PermissionError)


def _require_text(value: Any, field: str) -> str:
	if not isinstance(value, str) or not value.strip():
		frappe.throw(f"{field} is required.", frappe.ValidationError)
	return value.strip()


def _parse_intent(value: Any) -> tuple[str, list[dict[str, str]]] | None:
	if value is None:
		return None
	if not isinstance(value, dict) or set(value) != {"semantic_key", "evidence_refs"}:
		frappe.throw("Intent result has an unsupported shape.", frappe.ValidationError)
	semantic_key = _require_text(value.get("semantic_key"), "intent.semantic_key")
	refs = value.get("evidence_refs")
	if not isinstance(refs, list) or not refs:
		frappe.throw("Intent requires evidence references.", frappe.ValidationError)
	parsed = []
	for ref in refs:
		if not isinstance(ref, dict) or set(ref) != {"doctype", "name", "actor_role"}:
			frappe.throw("Intent evidence reference has an unsupported shape.", frappe.ValidationError)
		if ref.get("doctype") != "CRM Interaction Evidence" or ref.get("actor_role") != "student":
			frappe.throw(
				"Only student Interaction Evidence can substantiate an intent.", frappe.PermissionError
			)
		parsed.append({key: _require_text(ref.get(key), f"intent.evidence_refs.{key}") for key in ref})
	return semantic_key, parsed


def _parse_json(value: Any, field: str) -> Any:
	if isinstance(value, str):
		try:
			return json.loads(value)
		except (TypeError, ValueError):
			frappe.throw(f"{field} must be valid JSON.", frappe.ValidationError)
	return value


def _bounded_text(value: Any, field: str, maximum: int) -> str:
	if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
		frappe.throw(f"{field} is invalid or exceeds its bound.", frappe.ValidationError)
	text = value.strip()
	if any(ord(char) < 32 for char in text):
		frappe.throw(f"{field} contains a control character.", frappe.ValidationError)
	return text


def _safe_intelligence_text(value: Any, field: str, maximum: int) -> str:
	text = _bounded_text(value, field, maximum)
	without_dates = _ISO_DATE_OR_TIMESTAMP.sub("", text)
	if _PII_EMAIL.search(text) or _PII_PHONE.search(without_dates):
		frappe.throw(f"{field} contains a PII-shaped value.", frappe.ValidationError)
	return text


def _validate_decision_signals(value: Any, *, state: str) -> dict[str, Any]:
	value = _parse_json(value, "decision_signals")
	if not isinstance(value, Mapping) or set(value) != {"schema_revision", "observations"}:
		frappe.throw("decision_signals has an unsupported shape.", frappe.ValidationError)
	if value.get("schema_revision") != "nba-decision-signals-v1":
		frappe.throw("decision_signals schema revision is unsupported.", frappe.ValidationError)
	observations = value.get("observations")
	if not isinstance(observations, list) or len(observations) > 12:
		frappe.throw("decision_signals observations are unbounded.", frappe.ValidationError)
	allowed = {
		"need_code", "status", "basis", "confidence", "blocks_progress",
		"explicit_request", "advice_readiness", "application_readiness",
		"parent_influence", "evidence_refs",
	}
	need_codes = {
		"RESOLVE_MAJOR_UNCERTAINTY", "RESOLVE_FINANCIAL_UNCERTAINTY",
		"UNDERSTAND_CAREER_OUTLOOK",
	}
	for index, observation in enumerate(observations):
		if not isinstance(observation, Mapping) or set(observation) != allowed:
			frappe.throw(f"decision_signals.observations[{index}] is invalid.", frappe.ValidationError)
		if observation.get("need_code") not in need_codes:
			frappe.throw("decision signal need code is invalid.", frappe.ValidationError)
		if observation.get("status") not in {"open", "resolved", "denied", "uncertain"}:
			frappe.throw("decision signal status is invalid.", frappe.ValidationError)
		if observation.get("basis") not in {"explicit", "inferred"}:
			frappe.throw("decision signal basis is invalid.", frappe.ValidationError)
		if observation.get("confidence") not in {"low", "medium", "high", "unknown"}:
			frappe.throw("decision signal confidence is invalid.", frappe.ValidationError)
		for field in ("blocks_progress", "explicit_request"):
			if not isinstance(observation.get(field), bool):
				frappe.throw(f"decision signal {field} must be boolean.", frappe.ValidationError)
		if observation.get("advice_readiness") not in {"ready", "hesitant", "unknown"} or observation.get(
			"application_readiness"
		) not in {"ready", "hesitant", "unknown"}:
			frappe.throw("decision signal readiness is invalid.", frappe.ValidationError)
		if observation.get("parent_influence") not in {"concern", "high", "unknown"}:
			frappe.throw("decision signal parent influence is invalid.", frappe.ValidationError)
		refs = observation.get("evidence_refs")
		if not isinstance(refs, list) or not 1 <= len(refs) <= 4 or len(set(refs)) != len(refs):
			frappe.throw("decision signal evidence references are invalid.", frappe.ValidationError)
		for ref in refs:
			_bounded_text(ref, "decision signal evidence reference", 200)
	if state == "failed" and observations:
		frappe.throw("Failed interaction analysis cannot carry decision signals.", frappe.ValidationError)
	return {
		"schema_revision": value["schema_revision"],
		"observations": [dict(observation) for observation in observations],
	}


def _validate_intelligence(value: Any, *, state: str) -> dict[str, Any]:
	value = _parse_json(value, "intelligence")
	if state not in {"intent_bearing", "no_intent"} or not isinstance(value, Mapping):
		frappe.throw("intelligence is invalid for this interaction result.", frappe.ValidationError)
	allowed = {"summary", "sentiment", "entities", "readiness", "concerns"}
	if set(value) - allowed:
		frappe.throw("intelligence contains unsupported fields.", frappe.ValidationError)
	summary = value.get("summary", "")
	if not isinstance(summary, str) or "\n" in summary or "\r" in summary:
		frappe.throw("intelligence summary is invalid.", frappe.ValidationError)
	if summary:
		_safe_intelligence_text(summary, "intelligence.summary", 600)
	if value.get("sentiment") not in {None, "positive", "neutral", "negative", "mixed"}:
		frappe.throw("intelligence sentiment is invalid.", frappe.ValidationError)
	if value.get("readiness") not in {None, "ready", "hesitant", "unknown"}:
		frappe.throw("intelligence readiness is invalid.", frappe.ValidationError)
	entities = value.get("entities", {})
	if not isinstance(entities, Mapping) or len(entities) > 12:
		frappe.throw("intelligence entities are invalid.", frappe.ValidationError)
	for key, values in entities.items():
		if not isinstance(key, str) or not key.strip() or key.lower() in {
			"content", "raw_content", "transcript", "quoted_text", "email", "phone",
			"mobile", "student", "parent", "contact",
		}:
			frappe.throw("intelligence entity key is invalid.", frappe.ValidationError)
		if not isinstance(values, list) or len(values) > 12 or any(
			not isinstance(item, str) or not item.strip() or len(item) > 120 for item in values
		):
			frappe.throw("intelligence entity values are invalid.", frappe.ValidationError)
		for index, item in enumerate(values):
			_safe_intelligence_text(item, f"intelligence.entities.{key}[{index}]", 120)
	concerns = value.get("concerns", [])
	if not isinstance(concerns, list) or len(concerns) > 8 or any(
		 not isinstance(item, str) or not item.strip() or len(item) > 64 for item in concerns
	):
		frappe.throw("intelligence concerns are invalid.", frappe.ValidationError)
	for index, item in enumerate(concerns):
		_safe_intelligence_text(item, f"intelligence.concerns[{index}]", 64)
	return dict(value)


def claim_interaction_analysis_run(*, run_id: str, stage_generation: int) -> dict:
	"""Acquire the one service lease for a queued Interaction analysis stage."""
	_service_only()
	frappe.db.sql("SELECT name FROM `tabCRM Interaction Analysis Run` WHERE name=%s FOR UPDATE", (run_id,))
	run = frappe.get_doc("CRM Interaction Analysis Run", run_id)
	stage = frappe.db.get_value(
		"CRM Analysis Run Stage",
		{
			"parent_run_type": "CRM Interaction Analysis Run",
			"parent_run": run_id,
			"stage_kind": "interaction_analysis",
		},
		[
			"name",
			"stage_generation",
			"status",
			"expected_source_revision",
			"expected_source_digest",
			"lease_expires_at",
			*RULE_IDENTITY_FIELDS,
		],
		as_dict=True,
	)
	if not stage or int(stage.stage_generation or 0) != int(stage_generation):
		frappe.throw("Interaction analysis stage is stale.", frappe.ValidationError)
	if stage.status in {"completed", "abstained", "failed", "dead_lettered"}:
		return {"claimed": False, "status": stage.status}
	run_identity = _assert_run_ruleset_identity(run)
	_assert_stage_ruleset_identity(stage, run_identity)
	lease_expired = stage.status == "running" and (
		not stage.lease_expires_at or stage.lease_expires_at < frappe.utils.now_datetime()
	)
	if stage.status != "queued" and not lease_expired:
		return {"claimed": False, "status": stage.status}
	evidence = frappe.db.exists(
		"CRM Interaction Evidence",
		{"interaction": run.interaction, "source_revision": stage.expected_source_revision},
	)
	if not evidence:
		frappe.throw(
			"Interaction analysis evidence for this revision is unavailable.", frappe.ValidationError
		)
	lease_token = secrets.token_urlsafe(24)
	frappe.db.set_value(
		"CRM Analysis Run Stage",
		stage.name,
		{
			"status": "running",
			"lease_token": lease_token,
			"lease_expires_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), seconds=_LEASE_SECONDS),
		},
		update_modified=False,
	)
	frappe.db.set_value("CRM Interaction Analysis Run", run_id, "status", "running", update_modified=False)
	return {
		"claimed": True,
		"lease_token": lease_token,
		"stage_generation": int(stage.stage_generation),
		"source_revision": int(stage.expected_source_revision),
		"source_digest": stage.expected_source_digest,
		"interaction": run.interaction,
		**run_identity,
	}


def settle_interaction_analysis_result(
	*,
	run_id: str,
	stage_generation: int,
	lease_token: str,
	expected_source_revision: int,
	expected_source_digest: str,
	state: str,
	policy_revision: str,
	model_revision: str,
	result_digest: str,
	intent: dict[str, Any] | None = None,
	terminal_reason: str | None = None,
	rule_decision: dict[str, Any] | str | None = None,
	rule_version: str | None = None,
	rule_version_digest: str | None = None,
	ruleset_digest: str | None = None,
	decision_signals: dict[str, Any] | str | None = None,
	intelligence: dict[str, Any] | str | None = None,
	contract_version: str | None = None,
) -> dict:
	"""Atomically persist one fenced result and exactly one score trigger."""
	_service_only()
	if state not in _STATES:
		frappe.throw("Interaction analysis result state is invalid.", frappe.ValidationError)
	if not isinstance(stage_generation, int) or isinstance(stage_generation, bool) or stage_generation < 0:
		frappe.throw("Stage generation is invalid.", frappe.ValidationError)
	lease_token = _require_text(lease_token, "lease_token")
	if (
		not isinstance(expected_source_revision, int)
		or isinstance(expected_source_revision, bool)
		or expected_source_revision < 1
	):
		frappe.throw("Expected source revision is invalid.", frappe.ValidationError)
	if len(expected_source_digest or "") != 64 or len(result_digest or "") != 64:
		frappe.throw("Source and result digests must be SHA-256 values.", frappe.ValidationError)
	policy_revision = _require_text(policy_revision, "policy_revision")
	model_revision = _require_text(model_revision, "model_revision")
	parsed_intent = _parse_intent(intent)
	if state == "intent_bearing" and parsed_intent is None:
		frappe.throw("Intent-bearing results require an intent.", frappe.ValidationError)
	if state != "intent_bearing" and parsed_intent is not None:
		frappe.throw("Only intent-bearing results may include an intent.", frappe.ValidationError)
	try:
		validated_rule_decision = (
			validate_rule_decision(rule_decision) if rule_decision is not None else None
		)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
	identity_values = {
		"rule_version": rule_version,
		"rule_version_digest": rule_version_digest,
		"ruleset_digest": ruleset_digest,
	}
	if validated_rule_decision is not None:
		for fieldname in ("rule_version", "rule_version_digest", "ruleset_digest"):
			if identity_values[fieldname] in (None, ""):
				identity_values[fieldname] = validated_rule_decision[fieldname]
	if contract_version not in (None, "", "interaction-analysis-v2"):
		frappe.throw("Interaction analysis contract version is unsupported.", frappe.ValidationError)
	if contract_version == "interaction-analysis-v2" and decision_signals is None:
		frappe.throw("interaction-analysis-v2 requires decision signals.", frappe.ValidationError)
	if decision_signals is not None:
		decision_signals = _validate_decision_signals(decision_signals, state=state)
	if intelligence is not None:
		intelligence = _validate_intelligence(intelligence, state=state)
	digest_payload = {
		"run_id": run_id,
		"stage_generation": stage_generation,
		"expected_source_revision": expected_source_revision,
		"expected_source_digest": expected_source_digest,
		"state": state,
		"policy_revision": policy_revision,
		"model_revision": model_revision,
		"intent": intent,
	}
	if decision_signals is not None:
		digest_payload["decision_signals"] = decision_signals
	if validated_rule_decision is not None:
		digest_payload.update(
		{
			"rule_decision": validated_rule_decision,
			"rule_version": identity_values["rule_version"],
			"rule_version_digest": identity_values["rule_version_digest"],
			"ruleset_digest": identity_values["ruleset_digest"],
		}
	)
	expected_result_digest = _canonical_digest(digest_payload)
	if result_digest != expected_result_digest:
		frappe.throw("Interaction analysis result digest is invalid.", frappe.ValidationError)

	frappe.db.sql("SELECT name FROM `tabCRM Interaction Analysis Run` WHERE name=%s FOR UPDATE", (run_id,))
	run = frappe.get_doc("CRM Interaction Analysis Run", run_id)
	identity = _assert_run_ruleset_identity(run, identity_values)
	if validated_rule_decision is not None and (
		not identity
		or any(validated_rule_decision[field] != identity[field] for field in identity)
	):
		frappe.throw(
			"Interaction analysis rule decision does not match the pinned snapshot.",
			frappe.ValidationError,
		)
	stage = frappe.db.get_value(
		"CRM Analysis Run Stage",
		{
			"parent_run_type": "CRM Interaction Analysis Run",
			"parent_run": run_id,
			"stage_kind": "interaction_analysis",
		},
		[
			"name",
			"stage_generation",
			"expected_source_revision",
			"expected_source_digest",
			"status",
			"lease_token",
			"lease_expires_at",
			*RULE_IDENTITY_FIELDS,
		],
		as_dict=True,
	)
	if not stage:
		frappe.throw("Interaction analysis stage is unavailable.", frappe.DoesNotExistError)
	_assert_stage_ruleset_identity(stage, identity)
	frappe.db.sql("SELECT name FROM `tabCRM Analysis Run Stage` WHERE name=%s FOR UPDATE", (stage.name,))
	# Re-read after acquiring the row lock. A direct database writer may have
	# changed the read-only identity between the initial lookup and this fence;
	# settlement must validate the locked row, not a stale in-memory copy.
	stage = frappe.db.get_value(
		"CRM Analysis Run Stage",
		stage.name,
		[
			"name",
			"stage_generation",
			"expected_source_revision",
			"expected_source_digest",
			"status",
			"lease_token",
			"lease_expires_at",
			*RULE_IDENTITY_FIELDS,
		],
		as_dict=True,
	)
	if not stage:
		frappe.throw("Interaction analysis stage is unavailable.", frappe.DoesNotExistError)
	_assert_stage_ruleset_identity(stage, identity)
	if (
		int(stage.stage_generation or 0) != stage_generation
		or str(stage.expected_source_revision) != str(expected_source_revision)
		or stage.expected_source_digest != expected_source_digest
	):
		frappe.throw("Interaction analysis stage is stale.", frappe.ValidationError)
	if (
		int(run.source_revision or 0) != expected_source_revision
		or run.source_digest != expected_source_digest
	):
		frappe.throw("Interaction analysis run is stale.", frappe.ValidationError)
	expected_refs = json.dumps((parsed_intent or (None, []))[1], sort_keys=True, separators=(",", ":"))
	existing = frappe.db.get_value(
		"CRM Interaction Analysis Result",
		{"result_digest": result_digest},
		[
			"name",
			"analysis_run",
			"stage",
			"state",
			"source_revision",
			"source_digest",
			"policy_revision",
			"model_revision",
			"evidence_refs",
			"terminal_reason",
			"intent",
			"rule_version",
			"rule_version_digest",
			"ruleset_digest",
			"rule_decision",
		],
		as_dict=True,
	)
	if existing:
		existing_refs = existing.evidence_refs
		if isinstance(existing_refs, str):
			try:
				existing_refs = json.loads(existing_refs)
			except ValueError:
				existing_refs = None
		existing_refs = json.dumps(existing_refs, sort_keys=True, separators=(",", ":"))
		existing_semantic_key = None
		if existing.intent:
			existing_semantic_key = frappe.db.get_value("CRM Intent", existing.intent, "intent_type") or None
		expected_semantic_key = parsed_intent[0] if parsed_intent else None
		existing_rule_decision = (
			frappe.parse_json(existing.rule_decision) if existing.rule_decision else None
		)
		if (
			existing.analysis_run != run_id
			or existing.stage != stage.name
			or existing.state != state
			or int(existing.source_revision or 0) != expected_source_revision
			or existing.source_digest != expected_source_digest
			or existing.policy_revision != policy_revision
			or existing.model_revision != model_revision
			or existing_refs != expected_refs
			or (existing.terminal_reason or "") != (terminal_reason or "")[:500]
			or bool(existing.intent) != bool(parsed_intent)
			or existing_semantic_key != expected_semantic_key
			or {field: existing.get(field) for field in identity}
				!= (identity if identity else {})
			or existing_rule_decision != validated_rule_decision
		):
			frappe.throw(
				"Interaction analysis result digest conflicts with another settlement.",
				frappe.ValidationError,
			)
		return {
			"result": existing.name,
			**identity,
			"rule_decision": validated_rule_decision,
			"replayed": True,
		}
	if (
		stage.status != "running"
		or stage.lease_token != lease_token
		or stage.lease_expires_at < frappe.utils.now_datetime()
	):
		frappe.throw("Interaction analysis lease is invalid or expired.", frappe.PermissionError)
	if stage.status in {"completed", "abstained", "failed", "dead_lettered"}:
		frappe.throw("Interaction analysis stage is already terminal.", frappe.ValidationError)

	interaction_target = frappe.db.get_value(
		"CRM Interaction", run.interaction, ["student", "crm_contact"], as_dict=True
	)
	if not interaction_target:
		frappe.throw("Interaction analysis target is unavailable.", frappe.DoesNotExistError)
	student = interaction_target.student
	if parsed_intent:
		semantic_key, refs = parsed_intent
		for ref in refs:
			evidence = frappe.db.get_value(
				"CRM Interaction Evidence",
				ref["name"],
				["interaction", "student", "crm_contact", "source_revision", "evidence_digest", "actor_role"],
				as_dict=True,
			)
			if not evidence:
				frappe.throw("Intent evidence reference is unavailable.", frappe.ValidationError)
			if (
				evidence.interaction != run.interaction
				or evidence.student != interaction_target.student
				or evidence.crm_contact != interaction_target.crm_contact
				or int(evidence.source_revision or 0) != expected_source_revision
				or evidence.actor_role != "student"
			):
				frappe.throw(
					"Intent evidence reference is outside this analysis revision.", frappe.PermissionError
				)
		if not frappe.db.exists("CRM Intent Type", {"name": semantic_key, "enabled": 1}):
			frappe.throw("Intent type is not an active CRM Intent Type.", frappe.ValidationError)
		term = semantic_key
	else:
		refs = []
		term = None

	result = frappe.get_doc(
		{
			"doctype": "CRM Interaction Analysis Result",
			"analysis_run": run_id,
			"stage": stage.name,
			"state": state,
			"source_revision": expected_source_revision,
			"source_digest": expected_source_digest,
			"result_digest": result_digest,
			"policy_revision": policy_revision,
			"model_revision": model_revision,
			"evidence_refs": json.dumps(refs, sort_keys=True, separators=(",", ":")),
			"terminal_reason": (terminal_reason or "")[:500],
			"rule_version": identity.get("rule_version"),
			"rule_version_digest": identity.get("rule_version_digest"),
			"ruleset_digest": identity.get("ruleset_digest"),
			"rule_decision": json.dumps(validated_rule_decision, separators=(",", ":"))
			if validated_rule_decision
			else None,
			"contract_version": contract_version,
			"decision_signals": json.dumps(decision_signals, separators=(",", ":"))
			if decision_signals is not None
			else None,
			"intelligence": json.dumps(intelligence, ensure_ascii=False, separators=(",", ":"))
			if intelligence is not None
			else None,
		}
	).insert(ignore_permissions=True)
	intent_name = None
	if term:
		frappe.flags.interaction_analysis_result_service = True
		try:
			intent_doc = frappe.get_doc(
				{
					"doctype": "CRM Intent",
					"interaction": run.interaction,
					"student": student,
					"intent_type": term,
					"intent_role": "Dominant",
					"confidence": 100,
					"analysis_result": result.name,
				}
			).insert(ignore_permissions=True)
			intent_name = intent_doc.name
		finally:
			frappe.flags.interaction_analysis_result_service = False
		frappe.db.set_value(
			"CRM Interaction Analysis Result", result.name, "intent", intent_name, update_modified=False
		)

	terminal_status = (
		"completed"
		if state in {"no_intent", "intent_bearing"}
		else "abstained"
		if state == "unknown"
		else "failed"
	)
	frappe.db.set_value(
		"CRM Analysis Run Stage",
		stage.name,
		{
			"status": terminal_status,
			"policy_revision": policy_revision,
			"model_revision": model_revision,
			"result_digest": result_digest,
			"rule_decision": json.dumps(validated_rule_decision, separators=(",", ":"))
			if validated_rule_decision
			else None,
		},
		update_modified=False,
	)
	frappe.db.set_value(
		"CRM Interaction Analysis Run",
		run_id,
		{
			"status": terminal_status,
			"policy_revision": policy_revision,
			"model_revision": model_revision,
			"result_digest": result_digest,
		},
		update_modified=False,
	)
	if student:
		from crm.services.score_revision import bump_score_input_revision

		score_change = bump_score_input_revision(student, "interaction_analysis_settled")
	else:
		score_change = None
	from crm.api.interaction_read import publish_interaction_invalidation

	publish_interaction_invalidation(event_id=result.name)
	return {
		"result": result.name,
		"intent": intent_name,
		"score_change": score_change,
		**identity,
		"rule_decision": validated_rule_decision,
		"replayed": False,
	}
