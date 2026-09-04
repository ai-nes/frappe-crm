"""Strict shared contracts for durable Student and School Intelligence Runs.

This module deliberately contains no producer, scheduler, or result-settlement
behaviour.  Those belong to the later run-authority phase.  Keeping the
wire-shape validation here lets DocType controllers and future API commands
reject ambiguous or unsafe rows before any work is published.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe

RUN_STATUSES = frozenset({"queued", "running", "completed", "abstained", "failed", "dead_lettered"})
STAGE_KINDS = frozenset({"student_360", "school_360"})
TRIGGERS = frozenset({"automatic", "manual"})
CLAIM_KINDS = frozenset({"fact", "inference", "uncertainty", "recommendation"})
VISIBILITY_LABELS = frozenset({"shareable", "restricted", "service_only"})
MAX_IDEMPOTENCY_KEY_LENGTH = 140
MAX_SOURCE_REVISION_LENGTH = 64
MAX_PROVENANCE_IDS = 32
MAX_REVISION_LABEL_LENGTH = 160


def canonical_request_fingerprint(payload: dict[str, Any]) -> str:
	"""Return a stable digest for an allow-listed request payload only."""
	if not isinstance(payload, dict):
		raise ValueError("Analysis Run request must be an object.")
	allowed = {"domain", "target", "source_revision", "trigger", "force_reason", "policy_revision"}
	unknown = set(payload) - allowed
	if unknown:
		raise ValueError("Analysis Run request has unsupported fields.")
	canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
	return hashlib.sha256(canonical.encode()).hexdigest()


def validate_run_fields(doc) -> None:
	"""Validate immutable identity fields shared by both parent run DocTypes."""
	if doc.status not in RUN_STATUSES:
		frappe.throw("Invalid Analysis Run status.", frappe.ValidationError)
	if doc.trigger not in TRIGGERS:
		frappe.throw("Invalid Analysis Run trigger.", frappe.ValidationError)
	if not str(doc.source_revision or "").strip() or len(str(doc.source_revision)) > MAX_SOURCE_REVISION_LENGTH:
		frappe.throw("Analysis Run source revision is required and bounded.", frappe.ValidationError)
	if not str(doc.request_fingerprint or "").strip() or len(str(doc.request_fingerprint)) != 64:
		frappe.throw("Analysis Run request fingerprint must be a SHA-256 digest.", frappe.ValidationError)
	if doc.trigger == "manual" and not str(doc.requested_by or "").strip():
		frappe.throw("Manual Analysis Runs require an actor.", frappe.ValidationError)


def validate_stage_fields(doc) -> None:
	"""Reject cross-domain stage rows and unsafe stage idempotency keys."""
	if doc.stage_kind not in STAGE_KINDS:
		frappe.throw("Invalid Analysis Run stage kind.", frappe.ValidationError)
	if doc.status not in RUN_STATUSES:
		frappe.throw("Invalid Analysis Run stage status.", frappe.ValidationError)
	if not str(doc.stage_key or "").strip() or len(str(doc.stage_key)) > MAX_IDEMPOTENCY_KEY_LENGTH:
		frappe.throw("Analysis Run stage key is required and bounded.", frappe.ValidationError)
	if not str(doc.parent_run or "").strip() or doc.parent_run_type not in {
		"CRM Student Analysis Run",
		"CRM School Analysis Run",
	}:
		frappe.throw("Analysis Run stage parent is invalid.", frappe.ValidationError)
	if (doc.parent_run_type == "CRM Student Analysis Run") != (doc.stage_kind == "student_360"):
		frappe.throw("Analysis Run stage kind does not match its parent domain.", frappe.ValidationError)
	if (doc.parent_run_type == "CRM School Analysis Run") != (doc.stage_kind == "school_360"):
		frappe.throw("Analysis Run stage kind does not match its parent domain.", frappe.ValidationError)


def validate_claim_set(value: str | list[dict[str, Any]] | None) -> None:
	"""Validate bounded, provenance-labelled result claims without accepting raw evidence."""
	if not value:
		return
	claims = frappe.parse_json(value) if isinstance(value, str) else value
	if not isinstance(claims, list) or len(claims) > 100:
		frappe.throw("Analysis Run claims must be a bounded array.", frappe.ValidationError)
	for claim in claims:
		if not isinstance(claim, dict) or set(claim) - {"kind", "text", "provenance_ids", "visibility", "confidence"}:
			frappe.throw("Analysis Run claim has unsupported fields.", frappe.ValidationError)
		if claim.get("kind") not in CLAIM_KINDS or claim.get("visibility") not in VISIBILITY_LABELS:
			frappe.throw("Analysis Run claim kind or visibility is invalid.", frappe.ValidationError)
		if not isinstance(claim.get("text"), str) or not claim["text"].strip() or len(claim["text"]) > 2000:
			frappe.throw("Analysis Run claim text is invalid.", frappe.ValidationError)
		provenance_ids = claim.get("provenance_ids")
		if not isinstance(provenance_ids, list) or not provenance_ids or len(provenance_ids) > MAX_PROVENANCE_IDS:
			frappe.throw("Analysis Run claims require bounded provenance.", frappe.ValidationError)
		if any(not isinstance(item, str) or not item.strip() or len(item) > 160 for item in provenance_ids):
			frappe.throw("Analysis Run claim provenance is invalid.", frappe.ValidationError)
		confidence = claim.get("confidence")
		if confidence is not None and (not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1):
			frappe.throw("Analysis Run claim confidence is invalid.", frappe.ValidationError)


def validate_execution_revisions(policy_revision: str | None, model_revision: str | None, *, required: bool) -> None:
	"""Keep the reproducibility labels bounded and explicit at settlement."""
	for label, value in (("policy", policy_revision), ("model", model_revision)):
		if value is not None and (not str(value).strip() or len(str(value).strip()) > MAX_REVISION_LABEL_LENGTH):
			frappe.throw(f"Analysis Run {label} revision is invalid.", frappe.ValidationError)
	if required and (not str(policy_revision or "").strip() or not str(model_revision or "").strip()):
		frappe.throw("Completed Analysis Run stages require policy and model revisions.", frappe.ValidationError)
