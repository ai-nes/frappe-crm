"""Pure-data builders for the shared CRM intelligence reference contract.

This module intentionally has no Frappe imports.  Callers pass values already
resolved by Frappe permission/business services, while crm-agents validates the
same shape at its service boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Mapping, NotRequired, TypedDict


INTELLIGENCE_REFERENCE_CONTRACT_VERSION = "intelligence-reference-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,179}$")
_SOURCE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/ -]{0,179}$")


class SubjectRef(TypedDict, total=False):
	contract_version: Literal["intelligence-reference-v1"]
	kind: Literal["student", "school"]
	subject_id: str
	tenant_id: str
	admission_year: str
	cohort: str


class EvidenceRef(TypedDict, total=False):
	contract_version: Literal["intelligence-reference-v1"]
	evidence_id: str
	subject: SubjectRef
	source_kind: str
	source_id: str
	source_revision: str
	status: Literal["verified", "missing", "unavailable", "denied", "stale", "conflicting"]
	freshness: Literal["fresh", "stale", "unknown"]
	visibility: Literal["shareable", "source_scoped"]
	observed_at: str
	valid_at: str
	coverage_id: str


class Coverage(TypedDict):
	contract_version: Literal["intelligence-reference-v1"]
	coverage_id: str
	state: Literal["available", "missing", "unavailable", "denied", "truncated", "conflicting"]
	included_count: int
	omitted_count: int
	reason: NotRequired[str | None]


class FindingRef(TypedDict, total=False):
	contract_version: Literal["intelligence-reference-v1"]
	finding_id: str
	subject: SubjectRef
	kind: Literal["fact", "derived_signal", "inference", "risk", "opportunity", "unknown"]
	code: str
	evidence_refs: list[str]
	freshness: Literal["fresh", "stale", "unknown"]
	confidence: float | None


class DecisionRef(TypedDict, total=False):
	contract_version: Literal["intelligence-reference-v1"]
	decision_id: str
	domain: Literal["student_nba", "school_recommendation"]
	subject: SubjectRef
	disposition: Literal["recommend", "wait", "no_action", "abstain", "review"]
	policy_revision: str
	evidence_refs: list[str]
	finding_refs: list[str]
	expires_at: str | None
	abstention_reason: str | None


class OutcomeRef(TypedDict, total=False):
	contract_version: Literal["intelligence-reference-v1"]
	outcome_id: str
	subject: SubjectRef
	kind: Literal["impression", "decision", "execution", "verified_outcome", "correction"]
	status: str
	decision_id: NotRequired[str | None]
	source_revision: str
	verified: bool


def _required(value: Any, name: str) -> str:
	if not isinstance(value, str) or not value.strip() or len(value) > 180 or not _IDENTIFIER.fullmatch(value.strip()):
		raise ValueError(f"{name} must be a bounded non-empty string")
	return value.strip()


def _validate_subject(subject: SubjectRef) -> None:
	if not isinstance(subject, dict) or subject.get("contract_version") != INTELLIGENCE_REFERENCE_CONTRACT_VERSION:
		raise ValueError("subject reference is malformed")
	if subject.get("kind") not in {"student", "school"}:
		raise ValueError("subject kind is invalid")
	_required(subject.get("subject_id"), "subject_id")
	_required(subject.get("tenant_id"), "tenant_id")
	if subject.get("admission_year") is not None and not re.fullmatch(r"20[0-9]{2}", str(subject["admission_year"])):
		raise ValueError("admission_year must be a four-digit year")


def build_subject_ref(
	kind: Literal["student", "school"],
	subject_id: str,
	tenant_id: str,
	*,
	admission_year: str | None = None,
	cohort: str | None = None,
) -> SubjectRef:
	"""Build the canonical subject identity after Frappe scope resolution."""
	if kind not in {"student", "school"}:
		raise ValueError("unsupported intelligence subject kind")
	result: SubjectRef = {
		"contract_version": INTELLIGENCE_REFERENCE_CONTRACT_VERSION,
		"kind": kind,
		"subject_id": _required(subject_id, "subject_id"),
		"tenant_id": _required(tenant_id, "tenant_id"),
	}
	if admission_year is not None:
		if not isinstance(admission_year, str) or not re.fullmatch(r"20[0-9]{2}", admission_year):
			raise ValueError("admission_year must be a four-digit year")
		result["admission_year"] = admission_year
	if cohort is not None:
		result["cohort"] = _required(cohort, "cohort")
	return result


def build_evidence_ref(
	evidence_id: str,
	subject: SubjectRef,
	source_kind: str,
	source_id: str,
	source_revision: str,
	*,
	status: str = "verified",
	freshness: str = "unknown",
	visibility: str = "source_scoped",
	observed_at: str | None = None,
	valid_at: str | None = None,
	coverage_id: str | None = None,
) -> EvidenceRef:
	"""Build a lineage reference; callers must not use this to grant access."""
	_validate_subject(subject)
	if status not in {"verified", "missing", "unavailable", "denied", "stale", "conflicting"}:
		raise ValueError("unsupported intelligence evidence status")
	if freshness not in {"fresh", "stale", "unknown"}:
		raise ValueError("unsupported intelligence evidence freshness")
	if visibility not in {"shareable", "source_scoped"}:
		raise ValueError("unsupported intelligence evidence visibility")
	if not _SOURCE_IDENTIFIER.fullmatch(str(source_kind)) or not _SOURCE_IDENTIFIER.fullmatch(str(source_id)):
		raise ValueError("source identifiers are malformed")
	if status == "verified" and freshness == "stale":
		raise ValueError("verified evidence cannot be stale")
	if status in {"missing", "unavailable", "denied"} and visibility == "shareable":
		raise ValueError("unavailable evidence cannot be shareable")
	result: EvidenceRef = {
		"contract_version": INTELLIGENCE_REFERENCE_CONTRACT_VERSION,
		"evidence_id": _required(evidence_id, "evidence_id"),
		"subject": subject,
		"source_kind": _required(source_kind, "source_kind"),
		"source_id": _required(source_id, "source_id"),
		"source_revision": _required(source_revision, "source_revision"),
		"status": status,
		"freshness": freshness,
		"visibility": visibility,
	}
	for key, value in (("observed_at", observed_at), ("valid_at", valid_at), ("coverage_id", coverage_id)):
		if value is not None:
			result[key] = _required(value, key)
	return result


def build_coverage(
	coverage_id: str,
	state: Literal["available", "missing", "unavailable", "denied", "truncated", "conflicting"],
	included_count: int = 0,
	omitted_count: int = 0,
	*,
	reason: str | None = None,
) -> Coverage:
	if state not in {"available", "missing", "unavailable", "denied", "truncated", "conflicting"}:
		raise ValueError("unsupported coverage state")
	if not isinstance(included_count, int) or isinstance(included_count, bool) or not 0 <= included_count <= 1000:
		raise ValueError("included_count must be bounded")
	if not isinstance(omitted_count, int) or isinstance(omitted_count, bool) or not 0 <= omitted_count <= 1000:
		raise ValueError("omitted_count must be bounded")
	if state == "truncated" and omitted_count == 0:
		raise ValueError("truncated coverage must report omitted rows")
	if state != "truncated" and omitted_count:
		raise ValueError("only truncated coverage may omit rows")
	if state != "available" and not reason:
		raise ValueError("non-available coverage requires a reason")
	result: Coverage = {"contract_version": INTELLIGENCE_REFERENCE_CONTRACT_VERSION, "coverage_id": _required(coverage_id, "coverage_id"), "state": state, "included_count": included_count, "omitted_count": omitted_count}
	if reason is not None:
		result["reason"] = _required(reason, "reason")
	return result


def build_finding_ref(
	finding_id: str,
	subject: SubjectRef,
	kind: Literal["fact", "derived_signal", "inference", "risk", "opportunity", "unknown"],
	code: str,
	evidence_refs: list[str] | tuple[str, ...],
	*,
	freshness: Literal["fresh", "stale", "unknown"] = "unknown",
	confidence: float | None = None,
) -> FindingRef:
	_validate_subject(subject)
	if kind not in {"fact", "derived_signal", "inference", "risk", "opportunity", "unknown"}:
		raise ValueError("unsupported finding kind")
	if freshness not in {"fresh", "stale", "unknown"}:
		raise ValueError("unsupported finding freshness")
	refs = list(dict.fromkeys(evidence_refs))
	if not refs or len(refs) > 8:
		raise ValueError("finding evidence references must be bounded and distinct")
	if any(str(ref).count(":") < 2 for ref in refs):
		raise ValueError("finding evidence references must include source revision")
	if confidence is not None and (isinstance(confidence, bool) or not 0 <= confidence <= 1):
		raise ValueError("finding confidence is invalid")
	return {"contract_version": INTELLIGENCE_REFERENCE_CONTRACT_VERSION, "finding_id": _required(finding_id, "finding_id"), "subject": subject, "kind": kind, "code": _required(code, "code"), "evidence_refs": refs, "freshness": freshness, "confidence": confidence}


def build_decision_ref(
	decision_id: str,
	domain: Literal["student_nba", "school_recommendation"],
	subject: SubjectRef,
	disposition: Literal["recommend", "wait", "no_action", "abstain", "review"],
	policy_revision: str,
	*,
	evidence_refs: list[str] | tuple[str, ...] = (),
	finding_refs: list[str] | tuple[str, ...] = (),
	expires_at: str | None = None,
	abstention_reason: str | None = None,
) -> DecisionRef:
	_validate_subject(subject)
	if domain not in {"student_nba", "school_recommendation"}:
		raise ValueError("unsupported decision domain")
	if disposition not in {"recommend", "wait", "no_action", "abstain", "review"}:
		raise ValueError("unsupported decision disposition")
	if disposition == "recommend" and not expires_at:
		raise ValueError("recommendation decisions require expiry")
	if disposition in {"abstain", "review"} and not abstention_reason:
		raise ValueError("abstention/review decisions require a reason")
	if disposition == "recommend" and abstention_reason:
		raise ValueError("recommendation decisions cannot carry abstention reason")
	refs = list(dict.fromkeys(evidence_refs))[:8]
	if any(str(ref).count(":") < 2 for ref in refs):
		raise ValueError("decision evidence references must include source revision")
	return {"contract_version": INTELLIGENCE_REFERENCE_CONTRACT_VERSION, "decision_id": _required(decision_id, "decision_id"), "domain": domain, "subject": subject, "disposition": disposition, "policy_revision": _required(policy_revision, "policy_revision"), "evidence_refs": refs, "finding_refs": list(dict.fromkeys(finding_refs))[:8], "expires_at": expires_at, "abstention_reason": abstention_reason}


def build_outcome_ref(
	outcome_id: str,
	subject: SubjectRef,
	kind: Literal["impression", "decision", "execution", "verified_outcome", "correction"],
	status: str,
	source_revision: str,
	*,
	decision_id: str | None = None,
	verified: bool = False,
) -> OutcomeRef:
	_validate_subject(subject)
	if kind not in {"impression", "decision", "execution", "verified_outcome", "correction"}:
		raise ValueError("unsupported outcome kind")
	if kind == "verified_outcome" and not verified:
		raise ValueError("verified_outcome must be marked verified")
	result: OutcomeRef = {"contract_version": INTELLIGENCE_REFERENCE_CONTRACT_VERSION, "outcome_id": _required(outcome_id, "outcome_id"), "subject": subject, "kind": kind, "status": _required(status, "status"), "source_revision": _required(source_revision, "source_revision"), "verified": bool(verified)}
	if decision_id is not None:
		result["decision_id"] = _required(decision_id, "decision_id")
	return result


def reference_digest(value: Mapping[str, Any]) -> str:
	"""Use the same canonical JSON hashing rule as crm-agents."""
	if "decision_id" in value:
		value = {key: item for key, item in value.items() if key != "expires_at"}
	payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
	return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def finding_id(*, subject: SubjectRef, kind: str, code: str, evidence_refs: list[str] | tuple[str, ...]) -> str:
	return reference_digest({"subject": subject, "kind": kind, "code": code, "evidence_refs": sorted(evidence_refs)})[:32]
