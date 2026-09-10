"""Read-only consultation workspace admission over the existing NBA boundary."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import frappe

from crm.services.intelligence_refs import build_decision_ref, build_evidence_ref, build_subject_ref


@frappe.whitelist()
def get_consultation_workspace(recommendation: str) -> dict:
	rollout = str(frappe.conf.get("crm_intelligence_consultation_rollout_mode") or "disabled").strip().lower()
	if rollout not in {"shadow", "pilot"}:
		return {
			"contract_version": "consultation-workspace-v1",
			"status": "unavailable",
			"subject": None,
			"decision": None,
			"evidence": [],
			"findings": [],
			"context_revision": "unknown",
			"goal": None,
			"verified_facts": [],
			"risks": [],
			"opportunities": [],
			"missing_evidence": [],
			"verification_questions": [],
		}
	if not isinstance(recommendation, str) or not recommendation.strip():
		frappe.throw("recommendation is required.", frappe.ValidationError)
	doc = frappe.get_doc("CRM Recommendation", recommendation.strip())
	doc.check_permission("read")
	student = str(doc.get("target_id") or doc.get("student") or "")
	if not student or not frappe.has_permission("CRM Student", "read", student):
		return {"contract_version": "consultation-workspace-v1", "status": "denied", "recommendation": recommendation}
	current_revision = str(frappe.db.get_value("CRM Student", student, "student_context_revision") or 0)
	source_revision = str(doc.get("source_context_revision") or current_revision)
	if source_revision != current_revision:
		status = "stale"
	else:
		status = "ready"
	expires_at = doc.get("expires_at")
	if expires_at:
		try:
			expires_dt = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00")) if isinstance(expires_at, str) else expires_at
			if expires_dt.tzinfo is None:
				expires_dt = expires_dt.replace(tzinfo=timezone.utc)
			if expires_dt <= datetime.now(timezone.utc):
				status = "expired"
		except (AttributeError, TypeError, ValueError):
			pass
	ai_payload = doc.get("ai_payload")
	if isinstance(ai_payload, str):
		try:
			ai_payload = json.loads(ai_payload)
		except (TypeError, ValueError):
			ai_payload = {}
	ai_payload = ai_payload if isinstance(ai_payload, dict) else {}
	evidence_refs = tuple(str(ref) for ref in ai_payload.get("evidence_refs") or () if isinstance(ref, str))
	subject = build_subject_ref("student", student, str(frappe.local.site or "frappe"))
	evidence = []
	for raw in evidence_refs:
		prefix, separator, source_id = raw.partition(":")
		if separator and source_id:
			evidence.append(build_evidence_ref(f"{prefix}:{source_id}:{source_revision}", subject, prefix, source_id, source_revision, freshness="fresh", visibility="source_scoped"))
	decision = build_decision_ref(
		decision_id=str(doc.name),
		domain="student_nba",
		subject=build_subject_ref("student", student, str(frappe.local.site or "frappe")),
		disposition="recommend" if status == "ready" else "review",
		policy_revision=str(doc.get("decision_revision") or "nba-recommendation-policy"),
		evidence_refs=tuple(item["evidence_id"] for item in evidence),
		expires_at=str(expires_at) if status == "ready" and expires_at else None,
		abstention_reason=None if status == "ready" else f"consultation_{status}",
	)
	return {
		"contract_version": "consultation-workspace-v1",
		"status": status,
		"subject": subject,
		"decision": decision,
		"evidence": evidence,
		"context_revision": current_revision,
		"goal": doc.get("objective") or doc.get("reason") or None,
		"verified_facts": [
			item if isinstance(item, str) else str(item.get("summary") or item.get("statement") or "")
			for item in list(ai_payload.get("explanation_facts") or ())[:8]
			if isinstance(item, str) or isinstance(item, dict)
		],
		"findings": [],
		"risks": [],
		"opportunities": list(ai_payload.get("opportunity_refs") or ())[:5],
		"missing_evidence": [],
		"verification_questions": [],
	}
