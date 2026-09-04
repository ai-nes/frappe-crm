"""Authenticated API boundary for recording NBA learning feedback."""

from __future__ import annotations

import frappe
from frappe import _

from crm.fcrm.nba import record_nba_feedback


def _require_authenticated_user():
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	return frappe.session.user


@frappe.whitelist(methods=["POST"])
def record_feedback(
	recommendation: str,
	outcome: str,
	predicted_probability: float,
	actual_result: str,
	reward: float | None = None,
	actual_impact: float | None = None,
	feedback_source: str = "human",
	effectiveness_index: float | None = None,
	ai_confidence: float | None = None,
):
	"""Record one scoped, immutable Recommendation Feedback row.

	``predicted_probability`` remains a required compatibility-only history
	value; ``effectiveness_index`` and ``ai_confidence`` are the forward-looking
	quality signals and are optional so older clients keep working.
	"""
	_require_authenticated_user()
	recommendation_doc = frappe.get_doc("CRM Recommendation", recommendation)
	outcome_doc = frappe.get_doc("CRM Action Outcome", outcome)
	if not recommendation_doc.has_permission("read"):
		frappe.throw(_("Recommendation is outside the actor's scope."), frappe.PermissionError)
	if not outcome_doc.has_permission("read"):
		frappe.throw(_("Outcome is outside the actor's scope."), frappe.PermissionError)
	execution_doc = frappe.get_doc("CRM Action Execution", outcome_doc.execution)
	if execution_doc.recommendation != recommendation:
		frappe.throw(_("Execution does not belong to the Recommendation."), frappe.ValidationError)
	if not execution_doc.has_permission("read"):
		frappe.throw(_("Execution is outside the actor's scope."), frappe.PermissionError)
	return record_nba_feedback(
		recommendation=recommendation,
		outcome=outcome,
		predicted_probability=predicted_probability,
		actual_result=actual_result,
		reward=reward,
		actual_impact=actual_impact,
		feedback_source=feedback_source,
		task=execution_doc.get("task"),
		effectiveness_index=effectiveness_index,
		ai_confidence=ai_confidence,
	)
