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
	idempotency_key: str | None = None,
):
	"""Record one scoped, immutable Recommendation Feedback row.

	Feedback is accepted only when Recommendation, Outcome, and Student form
	one linked aggregate. The service helper owns idempotency and the insert.
	"""
	actor = _require_authenticated_user()
	recommendation_doc = frappe.get_doc("CRM Recommendation", recommendation)
	outcome_doc = frappe.get_doc("CRM Action Outcome", outcome)
	if not recommendation_doc.has_permission("read"):
		frappe.throw(_("Recommendation is outside the actor's scope."), frappe.PermissionError)
	if outcome_doc.recommendation != recommendation or outcome_doc.student != recommendation_doc.student:
		frappe.throw(_("Outcome does not belong to the Recommendation."), frappe.ValidationError)
	if not outcome_doc.has_permission("read"):
		frappe.throw(_("Outcome is outside the actor's scope."), frappe.PermissionError)
	execution_doc = frappe.get_doc("CRM Action Execution", outcome_doc.execution)
	if execution_doc.recommendation != recommendation or execution_doc.student != recommendation_doc.student:
		frappe.throw(_("Execution does not belong to the Recommendation."), frappe.ValidationError)
	if not execution_doc.has_permission("read"):
		frappe.throw(_("Execution is outside the actor's scope."), frappe.PermissionError)
	return record_nba_feedback(
		recommendation=recommendation,
		outcome=outcome,
		student=recommendation_doc.student,
		predicted_probability=predicted_probability,
		actual_result=actual_result,
		reward=reward,
		actual_impact=actual_impact,
		feedback_source=feedback_source,
		created_by=actor,
		idempotency_key=idempotency_key or frappe.get_request_header("Idempotency-Key"),
	)
