"""Permissioned, compare-and-set transitions for CRM Recommendations."""
import frappe
from frappe import _


@frappe.whitelist()
def transition_recommendation(name: str, expected_revision: str, status: str, decision_reason: str | None = None) -> dict:
	"""Apply a legal decision only if the client still holds the CRM revision.

	No caller-selected user, campus, or role scope is accepted. Frappe's own
	session plus document permission hooks determine visibility and authority.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	doc = frappe.get_doc("CRM Recommendation", name)
	if not doc.has_permission("write"):
		frappe.throw(_("You do not have permission to decide this recommendation."), frappe.PermissionError)
	if str(doc.modified) != expected_revision:
		frappe.throw(_("Recommendation changed; refresh before deciding."), frappe.ValidationError)
	doc.status = status
	doc.decision_reason = decision_reason
	doc.save()
	action = frappe.db.get_value("CRM Sales Action", {"recommendation": doc.name}, "name")
	return {"name": doc.name, "status": doc.status, "source_revision": str(doc.modified), "sales_action": action}


@frappe.whitelist()
def record_sales_action_outcome(
	name: str, expected_revision: str, business_outcome: str, outcome_notes: str | None = None
) -> dict:
	"""CAS-protected outcome entry for a Sales Action the caller may write."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	doc = frappe.get_doc("CRM Sales Action", name)
	if not doc.has_permission("write"):
		frappe.throw(_("You do not have permission to record this outcome."), frappe.PermissionError)
	if str(doc.modified) != expected_revision:
		frappe.throw(_("Sales Action changed; refresh before recording an outcome."), frappe.ValidationError)
	if business_outcome not in {
		"NO_RESPONSE", "INTEREST_INCREASED", "NEEDS_MORE_INFORMATION", "CALL_BACK_LATER",
		"APPLICATION_STARTED", "APPLICATION_COMPLETED", "NOT_INTERESTED",
	}:
		frappe.throw(_("Invalid business outcome."), frappe.ValidationError)
	doc.business_outcome = business_outcome
	doc.outcome_notes = outcome_notes
	doc.execution_status = "completed"
	doc.save()
	return {"name": doc.name, "source_revision": str(doc.modified)}


@frappe.whitelist()
def get_sales_action(name: str) -> dict:
	"""Return the small, permission-checked projection needed by the Desk outcome control."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)
	doc = frappe.get_doc("CRM Sales Action", name)
	if not doc.has_permission("read"):
		frappe.throw(_("You do not have permission to view this Sales Action."), frappe.PermissionError)
	return {"name": doc.name, "action_type": doc.action_type, "source_revision": str(doc.modified)}
