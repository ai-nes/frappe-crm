"""Pure Phase 5 qualification and continuity policy helpers.

Qualification is deliberately represented by evidence references rather than a
score.  This module contains no Frappe calls, so command services and context
readers can share the same invariants and tests can exercise them without a
bench.  The event service remains responsible for checking that referenced
documents are visible to the actor before persisting an event.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any

QUALIFICATION_POLICY_VERSION = "qualification"
ENGAGEMENT_POLICY_VERSION = "student-engagement"
MAX_WAITING_DAYS = 30

# These are contract values, not labels from a mutable master.  Unknown values
# must be rejected by the command instead of silently normalised.
OUTCOME_CODES = frozenset(
	{
		"connected",
		"qualified",
		"follow_up_required",
		"no_response",
		"not_interested",
		"invalid",
		"completed",
	}
)
MEANINGFUL_OUTCOMES = frozenset({"connected", "qualified", "follow_up_required", "completed"})

# Evidence categories are intentionally broad enough to reference existing
# Interaction/Task/appointment/document records, while excluding arbitrary
# source payloads from the public DTO.
EVIDENCE_CATEGORIES = frozenset({"intent", "appointment", "document", "outcome", "interaction"})
MQL_EVIDENCE_CATEGORIES = frozenset({"intent", "appointment", "document"})
APPLICANT_EVIDENCE_CATEGORIES = frozenset({"appointment", "document"})
QUALIFICATION_STAGES = ("MQL", "Applicant", "Enrolled")
EVIDENCE_DOCTYPES = {
	"intent": frozenset({"CRM Intent", "CRM Interaction"}),
	"appointment": frozenset({"CRM Appointment"}),
	"document": frozenset({"CRM Student Document", "File"}),
	"outcome": frozenset({"CRM Student Outcome"}),
	"interaction": frozenset({"CRM Interaction", "Task", "CRM Student Lifecycle Event"}),
}


class QualificationValidationError(ValueError):
	"""Raised when an outcome/evidence contract is not satisfied."""


def _as_list(value: Any) -> list[Any]:
	if value is None or value == "":
		return []
	if isinstance(value, (str, bytes, bytearray)):
		return [value]
	if isinstance(value, dict):
		return [value]
	if isinstance(value, Iterable):
		return list(value)
	return [value]


def normalize_evidence(evidence: Any) -> list[dict[str, str]]:
	"""Return safe, stable evidence references.

	Accepted references are dictionaries containing ``category`` (or the
	backwards-compatible ``type``), a doctype and a document name.  A compact
	``"category:doctype:name"`` form is accepted for command callers, but raw
	payloads, notes and arbitrary fields are discarded.  Duplicate references
	are removed while preserving input order.
	"""
	normalized: list[dict[str, str]] = []
	seen: set[tuple[str, str, str]] = set()
	for item in _as_list(evidence):
		if isinstance(item, str):
			parts = item.split(":", 2)
			if len(parts) == 1 and item.strip():
				# The UI accepts a compact event id.  Treat it as an outcome
				# reference; the command service still verifies existence,
				# Student linkage and permissions before persisting it.
				category, doctype, name = "outcome", "CRM Student Outcome", item
			elif len(parts) == 3:
				category, doctype, name = parts
			else:
				continue
		else:
			if not isinstance(item, dict):
				continue
			category = item.get("category") or item.get("type")
			doctype = item.get("doctype") or item.get("reference_doctype")
			name = item.get("name") or item.get("reference_name") or item.get("reference_docname")
		if not all(isinstance(part, str) and part.strip() for part in (category, doctype, name)):
			continue
		category, doctype, name = category.strip(), doctype.strip(), name.strip()
		if category not in EVIDENCE_CATEGORIES:
			continue
		key = (category, doctype, name)
		if key in seen:
			continue
		seen.add(key)
		normalized.append({"category": category, "doctype": doctype, "name": name})
	return normalized


def find_missing_qualification_evidence(
	target_stage: str | None,
	outcome_code: str | None,
	evidence: Any,
) -> list[str]:
	"""Return missing evidence requirements for a lifecycle target.

	``Lead`` and ``Lost`` do not require qualification evidence.  Active targets
	use cumulative gates, so a direct jump must satisfy the target and every
	stage it passes: MQL requires a qualifying outcome and an
	intent/appointment/document reference; Applicant adds an
	appointment/document reference; Enrolled retains all Applicant gates and a
	qualifying outcome.  References may satisfy more than one gate.  The
	function intentionally does not inspect an intent or score field: those
	values are informative only until a referenced evidence record is verified
	by the command service.
	"""
	stage = (target_stage or "").strip()
	if stage not in QUALIFICATION_STAGES:
		return []
	missing: list[str] = []
	refs = normalize_evidence(evidence)
	categories = {item["category"] for item in refs}
	for required_stage in QUALIFICATION_STAGES[: QUALIFICATION_STAGES.index(stage) + 1]:
		if required_stage == "MQL":
			if outcome_code not in MEANINGFUL_OUTCOMES:
				missing.append("qualifying_outcome")
			if not categories & MQL_EVIDENCE_CATEGORIES:
				missing.append("intent_or_appointment_or_document")
		elif required_stage == "Applicant" and not categories & APPLICANT_EVIDENCE_CATEGORIES:
			missing.append("appointment_or_document")
		elif required_stage == "Enrolled" and outcome_code not in MEANINGFUL_OUTCOMES:
			# A single existing outcome reference/code can prove the MQL and
			# Enrolled gate, so avoid reporting the same missing item twice.
			if "qualifying_outcome" not in missing:
				missing.append("qualifying_outcome")
	return missing


def validate_qualification_evidence(
	target_stage: str | None,
	outcome_code: str | None,
	evidence: Any,
	*,
	policy_version: str = QUALIFICATION_POLICY_VERSION,
) -> dict[str, Any]:
	"""Validate and return the event-safe qualification evidence projection."""
	if policy_version != QUALIFICATION_POLICY_VERSION:
		raise QualificationValidationError("Unsupported qualification policy version")
	if outcome_code is not None and outcome_code not in OUTCOME_CODES:
		raise QualificationValidationError("Unknown outcome code")
	normalized = normalize_evidence(evidence)
	for item in normalized:
		if item["doctype"] not in EVIDENCE_DOCTYPES.get(item["category"], frozenset()):
			raise QualificationValidationError("Evidence category does not match its DocType")
	missing = find_missing_qualification_evidence(target_stage, outcome_code, normalized)
	if missing:
		raise QualificationValidationError("Missing qualification evidence: " + ", ".join(missing))
	return {
		"policy_version": policy_version,
		"target_stage": target_stage,
		"outcome_code": outcome_code,
		"evidence": normalized,
		"evidence_categories": sorted({item["category"] for item in normalized}),
	}


def _coerce_datetime(value: Any) -> datetime | date | None:
	if isinstance(value, (datetime, date)):
		return value
	if not value:
		return None
	if isinstance(value, str):
		try:
			return datetime.fromisoformat(value.replace("Z", "+00:00"))
		except ValueError:
			try:
				return date.fromisoformat(value)
			except ValueError:
				return None
	return None


def validate_continuity(
	outcome_code: str | None,
	continuity_kind: str | None,
	*,
	next_action: dict[str, Any] | None = None,
	reason: str | None = None,
	expires_at: Any = None,
	now: datetime | date | None = None,
) -> dict[str, Any]:
	"""Validate meaningful interaction continuity and return a safe summary."""
	if outcome_code not in OUTCOME_CODES:
		raise QualificationValidationError("Unknown outcome code")
	kind = (continuity_kind or "").strip().lower()
	if outcome_code not in MEANINGFUL_OUTCOMES:
		return {"continuity_kind": kind or None, "meaningful": False}
	if kind == "task":
		if not isinstance(next_action, dict):
			raise QualificationValidationError("A meaningful task outcome requires a next action")
		if not next_action.get("student"):
			raise QualificationValidationError("Next action must link to the Student")
		if not next_action.get("assigned_to"):
			raise QualificationValidationError("Next action requires an assignee")
		if not next_action.get("due_date"):
			raise QualificationValidationError("Next action requires a due date")
		return {"continuity_kind": "task", "meaningful": True}
	if kind not in {"waiting", "terminal"}:
		raise QualificationValidationError("Meaningful outcome requires task, waiting, or terminal continuity")
	if not isinstance(reason, str) or not reason.strip():
		raise QualificationValidationError(f"{kind.title()} continuity requires a reason")
	if kind == "waiting":
		expires = _coerce_datetime(expires_at)
		current = now or datetime.now(expires.tzinfo if isinstance(expires, datetime) else None)
		if expires is None:
			raise QualificationValidationError("Waiting continuity requires an expiry")
		comparison_current = current.date() if isinstance(expires, date) and not isinstance(expires, datetime) and isinstance(current, datetime) else current
		if expires <= comparison_current:
			raise QualificationValidationError("Waiting continuity expiry must be in the future")
		if expires > comparison_current + timedelta(days=MAX_WAITING_DAYS):
			raise QualificationValidationError("Waiting continuity cannot exceed 30 days")
		return {"continuity_kind": "waiting", "meaningful": True, "expires_at": expires}
	# Terminal has no follow-up task or expiry; a reason is its audit evidence.
	return {"continuity_kind": "terminal", "meaningful": True}


def redact_evidence(evidence: Any) -> list[dict[str, str]]:
	"""Return only public reference fields for context responses."""
	return normalize_evidence(evidence)
