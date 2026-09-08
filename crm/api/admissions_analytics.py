"""Privacy-preserving aggregate reads for the CRM copilot roles.

The endpoint intentionally returns cohort/pipeline counts only.  Individual
student names, emails, phones and CRM identifiers never leave this boundary.
"""
from collections import Counter

import frappe
from frappe import _

from crm.api.capability import _is_capability_gateway_user
from crm.api.session import get_session_role_flags

_ALLOWED_ROLES = frozenset({
	"Sale", "CTV Sale", "Lead Sale", "Marketing", "Lead Marketing",
	"Promoter", "Lead Promoter", "Admissions Director",
})


def _require_role() -> None:
	if not _is_capability_gateway_user(get_session_role_flags()):
		frappe.throw(_("You are not permitted to access aggregate admissions analytics."), frappe.PermissionError)
	roles = set(frappe.get_roles())
	if not _ALLOWED_ROLES.intersection(roles):
		frappe.throw(_("You are not permitted to access aggregate admissions analytics."), frappe.PermissionError)
	if not frappe.db.exists(
		"CRM Staff", {"user": frappe.session.user}
	):
		frappe.throw(_("A CRM Staff campus mapping is required for aggregate analytics."), frappe.PermissionError)


def _count(values: list[str | None]) -> dict[str, int]:
	return dict(sorted(Counter(value or "Unknown" for value in values).items()))


@frappe.whitelist()
def get_pipeline_summary() -> dict:
	"""Return aggregate admissions metrics for the caller's visible Student rows.

	The endpoint is aggregate-only, but the source Student set is still loaded
	through Frappe's permission-aware list API. A caller's campus mapping is an
	additional ceiling, never a replacement for canonical Student row scope.
	"""
	_require_role()
	staff_campus = frappe.db.get_value("CRM Staff", {"user": frappe.session.user}, "campus")
	student_filters = {}
	if staff_campus:
		student_filters["branch"] = staff_campus
	students = frappe.get_list(
		"CRM Lead",
		filters=student_filters,
		fields=["name", "enrollment_status", "source", "branch"],
		limit_page_length=500,
		order_by="name asc",
	)
	student_ids = [row.name for row in students]
	if not student_ids:
		return {
			"cohort": "CRM-SCOPED", "total_students": 0,
			"by_enrollment_status": {}, "by_source": {}, "by_campus": {},
			"intent_count": 0, "interaction_count": 0,
			"unresolved_interactions": 0, "active_actions": 0,
			"actions_by_state": {},
		}

	interactions = frappe.get_list(
		"CRM Interaction", filters={"student": ["in", student_ids]},
		fields=["student", "outcome"], limit_page_length=1000,
	)
	intents = frappe.get_list(
		"CRM Intent", filters={"student": ["in", student_ids]},
		fields=["student"], limit_page_length=1000,
	)
	actions = frappe.get_list(
		"CRM Action Item",
		filters={
			"student": ["in", student_ids],
			"current_slot": "CURRENT",
			"state": ["in", ["pending", "accepted", "in-progress", "requires-review", "deferred"]],
		},
		fields=["student", "state as status"], limit_page_length=1000,
	)
	return {
		"cohort": "CRM-SCOPED",
		"total_students": len(students),
		"by_enrollment_status": _count([row.enrollment_status for row in students]),
		"by_source": _count([row.source for row in students]),
		"by_campus": _count([row.branch for row in students]),
		"intent_count": len(intents),
		"interaction_count": len(interactions),
		"unresolved_interactions": sum(not row.outcome or row.outcome == "No Response" for row in interactions),
		"active_actions": len(actions),
		"actions_by_state": _count([row.status for row in actions]),
	}
