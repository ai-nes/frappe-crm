"""Shared read-model projection for one ``CRM Recommendation`` row.

Used by both the Sale worklist (`student_worklist.py`) and the Director
review queue (`director_next_best_action.py`) so a client only has to learn
one nested shape: ``title -> target -> action -> priority -> reason ->
objective -> timing -> status``. Deliberately excludes the raw
``ai_payload``/legacy flat fields those two callers still carry alongside
this for the accept/edit decision flow -- this view is display-only, never
the identity/diff source.
"""
from __future__ import annotations

from typing import Any

import frappe

from crm.fcrm.action_type_catalog import display_name_for_wire_action_code
from crm.services.intelligence_refs import build_decision_ref, build_subject_ref


def recommendation_view(
	*,
	recommendation_id: str,
	target_type: str,
	target_id: str | None,
	action_code: str | None,
	priority: str | None,
	rank: int | None,
	reason: str | None,
	explanation: dict[str, Any] | None,
	ai_payload: dict[str, Any] | None,
	expires_at_iso: str | None,
	lifecycle_status: str | None,
	decision_status: str | None,
	execution_status: str | None,
) -> dict[str, Any]:
	explanation = explanation if isinstance(explanation, dict) else {}
	action = explanation.get("action") if isinstance(explanation.get("action"), dict) else {}
	action_title = action.get("title") or display_name_for_wire_action_code(action_code) or action_code
	# Narration is best-effort and fails closed to no explanation (see
	# narrate_recommendation); every card must still carry an objective, so
	# fall back to the kernel-composed, always-populated `reason` rather than
	# leaving the field null and giving cards an inconsistent FE contract.
	objective = explanation.get("objective") or reason or None

	timing = ai_payload.get("recommended_timing") if isinstance(ai_payload, dict) else None
	timing = timing if isinstance(timing, dict) else {}

	context = explanation.get("context")
	decision_ref = None
	if isinstance(target_id, str) and target_id:
		kind = "student" if str(target_type or "").casefold() in {"student", "crm student", "lead", "crm lead"} else "school"
		try:
			expires = expires_at_iso if lifecycle_status not in {"completed", "cancelled", "rejected", "superseded"} else None
			disposition = "recommend" if expires else "no_action"
			decision_ref = build_decision_ref(
				decision_id=recommendation_id,
				domain="student_nba" if kind == "student" else "school_recommendation",
				subject=build_subject_ref(kind, target_id, str(frappe.local.site or "frappe")),
				disposition=disposition,
				policy_revision="nba-recommendation-policy",
				evidence_refs=tuple(ai_payload.get("evidence_refs") or ()) if isinstance(ai_payload, dict) else (),
				expires_at=expires,
			)
		except (TypeError, ValueError):
			# A recommendation with malformed lineage stays visible in the legacy
			# card, but it cannot masquerade as a governed DecisionRef.
			decision_ref = None

	return {
		"id": recommendation_id,
		"title": explanation.get("title") or action_title,
		"target": {"type": target_type, "id": target_id},
		"action": {"code": action_code, "title": action_title},
		"priority": priority or "medium",
		"rank": rank,
		"reason": reason or "",
		"objective": objective,
		"context": context if isinstance(context, list) else [],
		"timing": {
			"scheduled_at": timing.get("scheduled_at"),
			"selected_window": timing.get("selected_window"),
			"expires_at": expires_at_iso,
			"timezone": timing.get("timezone"),
		},
		"status": {
			"lifecycle": lifecycle_status,
			"decision": decision_status,
			"execution": execution_status,
		},
		"decision_ref": decision_ref,
	}
