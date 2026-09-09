"""Frappe-owned settlement command for Interaction analysis results."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

import frappe

from crm.fcrm.interaction_semantics import (
	INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION,
	INTELLIGENCE_SUMMARY_MAX_CHARS,
	InteractionContractError,
	validate_intelligence,
)
from crm.fcrm.nba_context import validate_decision_signals

_STATES = {"no_intent", "intent_bearing", "unknown", "failed"}
_LEASE_SECONDS = 120


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


def _parse_decision_signals(value: Any) -> dict | None:
	if value is None:
		return None
	try:
		return validate_decision_signals(value)
	except ValueError as exc:
		frappe.throw(str(exc), frappe.ValidationError)


def _parse_intelligence(value: Any, *, state: str) -> dict | None:
	"""Validate the additive, non-digest-bound conversation intelligence block."""
	if value is None:
		return None
	try:
		validate_intelligence(value, state=state)
	except InteractionContractError as exc:
		frappe.throw(str(exc), frappe.ValidationError)
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
		],
		as_dict=True,
	)
	if not stage or int(stage.stage_generation or 0) != int(stage_generation):
		frappe.throw("Interaction analysis stage is stale.", frappe.ValidationError)
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
	contract_version: str | None = None,
	intent: dict[str, Any] | None = None,
	decision_signals: dict[str, Any] | None = None,
	terminal_reason: str | None = None,
	intelligence: dict[str, Any] | None = None,
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
	parsed_signals = _parse_decision_signals(decision_signals)
	if contract_version not in {None, INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION}:
		frappe.throw("Interaction analysis contract version is invalid.", frappe.ValidationError)
	if decision_signals is not None and contract_version != INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION:
		frappe.throw("Decision signals require interaction-analysis-v2.", frappe.ValidationError)
	if decision_signals is None and contract_version == INTERACTION_ANALYSIS_RESULT_CONTRACT_VERSION:
		frappe.throw("Interaction-analysis-v2 requires decision signals.", frappe.ValidationError)
	# Additive, non-digest-bound: validated but never folded into result_digest,
	# so an omitted block keeps the byte-identical legacy digest contract.
	parsed_intelligence = _parse_intelligence(intelligence, state=state)
	if state == "failed" and parsed_signals and parsed_signals.get("observations"):
		frappe.throw("Failed interaction analysis results cannot carry decision signals.", frappe.ValidationError)
	if state == "intent_bearing" and parsed_intent is None:
		frappe.throw("Intent-bearing results require an intent.", frappe.ValidationError)
	if state != "intent_bearing" and parsed_intent is not None:
		frappe.throw("Only intent-bearing results may include an intent.", frappe.ValidationError)
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
	# Omitted signals retain the byte-identical legacy digest contract.  An
	# explicit empty object is meaningful and is therefore bound to the digest.
	if decision_signals is not None:
		digest_payload["decision_signals"] = parsed_signals
	expected_result_digest = _canonical_digest(digest_payload)
	if result_digest != expected_result_digest:
		frappe.throw("Interaction analysis result digest is invalid.", frappe.ValidationError)

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
			"expected_source_revision",
			"expected_source_digest",
			"status",
			"lease_token",
			"lease_expires_at",
		],
		as_dict=True,
	)
	if not stage:
		frappe.throw("Interaction analysis stage is unavailable.", frappe.DoesNotExistError)
	frappe.db.sql("SELECT name FROM `tabCRM Analysis Run Stage` WHERE name=%s FOR UPDATE", (stage.name,))
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
			"decision_signals",
		],
		as_dict=True,
	)
	if existing:
		existing_refs = existing.evidence_refs
		existing_signals = existing.decision_signals
		if isinstance(existing_signals, str):
			try:
				existing_signals = json.loads(existing_signals)
			except ValueError:
				existing_signals = None
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
		existing_signals = json.dumps(existing_signals, sort_keys=True, separators=(",", ":"))
		expected_signals = json.dumps(parsed_signals, sort_keys=True, separators=(",", ":"))
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
			or existing_signals != expected_signals
		):
			frappe.throw(
				"Interaction analysis result digest conflicts with another settlement.",
				frappe.ValidationError,
			)
		# First settlement wins. `intelligence` is outside the digest, so a
		# re-run with a different summary/sentiment is intentionally not
		# re-applied -- the persisted block reflects the first result.
		return {
			"result": existing.name,
			"replayed": True,
			"student": frappe.db.get_value("CRM Interaction", run.interaction, "student"),
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
	if parsed_signals:
		for observation in parsed_signals["observations"]:
			for evidence_ref in observation["evidence_refs"]:
				evidence = frappe.db.get_value(
					"CRM Interaction Evidence", evidence_ref,
					["interaction", "student", "crm_contact", "source_revision", "evidence_digest", "actor_role"],
					as_dict=True,
				)
				if not evidence:
					frappe.throw("Decision signal evidence reference is unavailable.", frappe.ValidationError)
				if (
					evidence.interaction != run.interaction
					or evidence.student != interaction_target.student
					or evidence.crm_contact != interaction_target.crm_contact
					or int(evidence.source_revision or 0) != expected_source_revision
					or evidence.actor_role != "student"
				):
					# ``evidence_digest`` fingerprints one labelled turn; the
					# parent ``source_digest`` fingerprints the complete revision.
					# Revision/interaction identity is the cross-row fence here.
					frappe.throw("Decision signal evidence is outside this analysis revision.", frappe.PermissionError)
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
				# ``evidence_digest`` is per turn, whereas ``source_digest`` is
				# the digest of the complete labelled revision.
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
			"decision_signals": json.dumps(parsed_signals, sort_keys=True, separators=(",", ":"))
			if parsed_signals is not None else None,
			"terminal_reason": (terminal_reason or "")[:500],
			"conversation_summary": (parsed_intelligence or {}).get("summary", "")[
				:INTELLIGENCE_SUMMARY_MAX_CHARS
			],
		}
	).insert(ignore_permissions=True)
	intent_name = None
	if term:
		# sentiment/readiness/concerns/entities hang off the CRM Intent row, so
		# on a no_intent result only `conversation_summary` (on the result doc
		# above) persists -- there is no intent row to carry the rest.
		frappe.flags.interaction_analysis_result_service = True
		try:
			_intel = parsed_intelligence or {}
			intent_doc = frappe.get_doc(
				{
					"doctype": "CRM Intent",
					"interaction": run.interaction,
					"student": student,
					"intent_type": term,
					"intent_role": "Dominant",
					"confidence": 100,
					"analysis_result": result.name,
					"sentiment": _intel.get("sentiment") or None,
					"readiness": _intel.get("readiness") or None,
					"concerns": json.dumps(_intel.get("concerns") or [], separators=(",", ":")),
					"entities": json.dumps(_intel.get("entities") or {}, sort_keys=True, separators=(",", ":")),
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
		"replayed": False,
		"student": student,
	}
