"""Thin HTTP adapters for Phase 6 decision commands."""
from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from crm.fcrm.student_decision import (
	StudentDecisionError,
	decide_recommendation as _decide_recommendation,
	reassign_sales_action as _reassign_sales_action,
	transition_sales_action as _transition_sales_action,
)


def _call(fn, **kwargs):
	try:
		return fn(**kwargs)
	except StudentDecisionError as exc:
		exc_type = frappe.PermissionError if exc.code in {"UNAUTHORIZED", "FORBIDDEN", "OUT_OF_SCOPE", "CONTRACT_UNAVAILABLE", "OUTBOX_DISABLED"} else frappe.ValidationError
		frappe.throw(str(exc), exc_type)


@frappe.whitelist(methods=["POST"])
def transition_recommendation(name: str, expected_revision: str, status: str, decision_reason: str | None = None, **kwargs):
	"""Compatibility adapter for the pre-Phase-6 Desk/demo call shape.

	New clients must send an idempotency key and the decision revision. This
	adapter only translates legacy callers; it does not restore direct document
	writes or bypass the Phase 6 command service.
	"""
	if kwargs.get("idempotency_key"):
		return _call(
			_decide_recommendation,
			name=name,
			expected_revision=expected_revision,
			status=status,
			decision_reason=decision_reason,
			due_at=kwargs.get("due_at"),
			assignee_staff=kwargs.get("assignee_staff"),
			revisit_at=kwargs.get("revisit_at"),
			defer_kind=kwargs.get("defer_kind"),
			idempotency_key=kwargs["idempotency_key"],
			correlation_id=kwargs.get("correlation_id"),
		)
	doc = frappe.get_doc("CRM Recommendation", name)
	legacy_modified = str(doc.modified) == str(expected_revision)
	result = _call(
		_decide_recommendation,
		name=name,
		expected_revision=(doc.get("decision_revision") or 0) if legacy_modified else expected_revision,
		status=status,
		decision_reason=decision_reason,
		due_at=kwargs.get("due_at") or doc.get("recommended_timing") or now_datetime(),
		revisit_at=kwargs.get("revisit_at"),
		defer_kind=kwargs.get("defer_kind"),
		idempotency_key=kwargs.get("idempotency_key") or f"legacy-decision-{name}-{expected_revision}-{status}",
		correlation_id=kwargs.get("correlation_id") or f"legacy-decision-{name}",
		expected_modified=str(expected_revision) if legacy_modified else None,
	)
	result.setdefault("name", result.get("recommendation"))
	return result


@frappe.whitelist(methods=["POST"])
def decide_recommendation(**kwargs):
	return _call(_decide_recommendation, **kwargs)


@frappe.whitelist(methods=["POST"])
def record_sales_action_outcome(name: str, expected_revision: str, business_outcome: str, outcome_notes: str | None = None):
	"""Compatibility adapter for the retired one-call completion endpoint."""
	action = frappe.get_doc("CRM Sales Action", name)
	result = _call(
		_transition_sales_action,
		name=name,
		expected_revision=action.get("action_revision") or 1,
		status="completed",
		outcome_code=business_outcome,
		evidence=outcome_notes,
		idempotency_key=f"legacy-outcome-{name}-{expected_revision}",
		correlation_id=f"legacy-outcome-{name}",
		expected_modified=str(expected_revision) if str(action.modified) == str(expected_revision) else None,
	)
	result.setdefault("name", result.get("sales_action"))
	return result


@frappe.whitelist(methods=["POST"])
def transition_sales_action(**kwargs):
	kwargs.pop("_internal_service", None)
	return _call(_transition_sales_action, **kwargs)


@frappe.whitelist(methods=["POST"])
def reassign_sales_action(**kwargs):
	kwargs.pop("_internal_service", None)
	return _call(_reassign_sales_action, **kwargs)


@frappe.whitelist()
def get_sales_action(name: str) -> dict:
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	doc = frappe.get_doc("CRM Sales Action", name)
	if not doc.has_permission("read"):
		frappe.throw("You do not have permission to view this Sales Action.", frappe.PermissionError)
	return {"name": doc.name, "student": doc.student, "action_type": doc.action_type, "status": doc.execution_status, "revision": doc.get("action_revision") or 1}
