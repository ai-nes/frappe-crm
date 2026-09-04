"""Versioned score-policy endpoint for crm-agents. Resolves this Frappe
instance's canonical answer to "which policy_revision / policy_hash is
currently active, and exactly what does it contain" — the previously-missing
authoritative score-template calculation contract."""

import frappe

from crm.fcrm.scoring_policy import get_active_policy


def _require_agent_identity():
	if frappe.session.user == "Guest":
		frappe.throw("Authentication is required.", frappe.PermissionError)
	configured = frappe.conf.get("crm_agents_service_user")
	if frappe.session.user == "Administrator":
		return
	if not configured or frappe.session.user != configured:
		frappe.throw(
			"This endpoint is restricted to the crm-agents service identity.", frappe.PermissionError
		)


@frappe.whitelist()
def get_active_score_policy() -> dict:
	"""Return the fully resolved, versioned policy for the single Active CRM
	Score Template, or an explicit `{"policy": None}` when none is Active —
	never a partial/empty policy silently treated as "zero rules apply"."""
	_require_agent_identity()
	policy = get_active_policy()
	return {"policy": policy}
