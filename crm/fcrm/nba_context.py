"""Canonical NBA decision-signal vocabulary shared with crm-agents.

This module is deliberately pure.  Frappe owns the evidence and stamps source
metadata when projecting settled observations; the agent only produces the
bounded observation payload defined here.
"""

from __future__ import annotations

from collections.abc import Mapping

from crm.fcrm.nba_canonical import canonical_digest

DECISION_SIGNALS_SCHEMA_REVISION = "nba-decision-signals-v1"
DECISION_SIGNALS_CONTENT_SPEC = (
	'{"basis":["explicit","inferred"],"confidence":["low","medium","high","unknown"],'
	'"coverage":["complete","partial","unavailable"],"max_evidence_refs":4,"max_observations":12,'
	'"need_codes":["RESOLVE_MAJOR_UNCERTAINTY","RESOLVE_FINANCIAL_UNCERTAINTY","UNDERSTAND_CAREER_OUTLOOK"],'
	'"parent_influence":["concern","high","unknown"],"projected_fields":["signal_id","source_interaction",'
	'"source_revision","source_digest","occurred_at","model_revision","prompt_revision"],'
	'"readiness":["ready","hesitant","unknown"],"schema_revision":"nba-decision-signals-v1",'
	'"settlement_fields":["need_code","status","basis","confidence","blocks_progress","explicit_request",'
	'"advice_readiness","application_readiness","parent_influence","evidence_refs"],'
	'"status":["open","resolved","denied","uncertain"]}'
)
DECISION_SIGNALS_CONTENT_HASH = "14930199a827a8df3a9eb11f8f82823c40267cf5ff50f4d575f27fe65374e0a0"
NBA_ENGINE_NAME = "nba-engine"
NEED_CODES = frozenset(
	{
		"RESOLVE_MAJOR_UNCERTAINTY",
		"RESOLVE_FINANCIAL_UNCERTAINTY",
		"UNDERSTAND_CAREER_OUTLOOK",
	}
)
SIGNAL_STATUSES = frozenset({"open", "resolved", "denied", "uncertain"})
SIGNAL_BASES = frozenset({"explicit", "inferred"})
SIGNAL_CONFIDENCE = frozenset({"low", "medium", "high", "unknown"})
READINESS = frozenset({"ready", "hesitant", "unknown"})
PARENT_INFLUENCE = frozenset({"concern", "high", "unknown"})
MAX_OBSERVATIONS = 12
MAX_EVIDENCE_REFS = 4

_OBSERVATION_KEYS = frozenset(
	{
		"need_code", "status", "basis", "confidence", "blocks_progress",
		"explicit_request", "advice_readiness", "application_readiness",
		"parent_influence", "evidence_refs",
	}
)


def _text(value: object, field: str) -> str:
	if not isinstance(value, str) or not value.strip():
		raise ValueError(f"{field} is required")
	return value.strip()


def validate_decision_signals(value: object, *, allow_empty: bool = True) -> dict:
	if not isinstance(value, Mapping):
		raise ValueError("decision_signals must be an object")
	if set(value) != {"schema_revision", "observations"}:
		raise ValueError("decision_signals has unsupported fields")
	if value.get("schema_revision") != DECISION_SIGNALS_SCHEMA_REVISION:
		raise ValueError("unsupported decision_signals schema revision")
	observations = value.get("observations")
	if not isinstance(observations, list) or len(observations) > MAX_OBSERVATIONS:
		raise ValueError("decision_signals observations are invalid")
	if not allow_empty and not observations:
		raise ValueError("decision_signals observations cannot be empty")
	result = []
	for item in observations:
		if not isinstance(item, Mapping) or set(item) != _OBSERVATION_KEYS:
			raise ValueError("decision observation has unsupported fields")
		row = dict(item)
		row["need_code"] = _text(row.get("need_code"), "need_code")
		if row["need_code"] not in NEED_CODES:
			raise ValueError("unsupported decision need code")
		for field, allowed in (
			("status", SIGNAL_STATUSES), ("basis", SIGNAL_BASES),
			("confidence", SIGNAL_CONFIDENCE), ("advice_readiness", READINESS),
			("application_readiness", READINESS), ("parent_influence", PARENT_INFLUENCE),
		):
			if row.get(field) not in allowed:
				raise ValueError(f"unsupported decision observation {field}")
		if not isinstance(row.get("blocks_progress"), bool) or not isinstance(row.get("explicit_request"), bool):
			raise ValueError("decision observation boolean fields are invalid")
		refs = row.get("evidence_refs")
		if not isinstance(refs, list) or not 0 < len(refs) <= MAX_EVIDENCE_REFS:
			raise ValueError("decision observation evidence_refs are invalid")
		if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
			raise ValueError("decision observation evidence_refs must be strings")
		row["evidence_refs"] = list(dict.fromkeys(refs))
		if len(row["evidence_refs"]) != len(refs):
			raise ValueError("decision observation evidence_refs must be distinct")
		result.append(row)
	return {"schema_revision": DECISION_SIGNALS_SCHEMA_REVISION, "observations": result}


def decision_signals_digest(value: Mapping) -> str:
	return canonical_digest(validate_decision_signals(value))
