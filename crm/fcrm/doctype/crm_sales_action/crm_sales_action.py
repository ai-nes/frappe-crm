import hashlib

import frappe
from frappe import _
from frappe.model.document import Document


class CRMSalesAction(Document):
	def autoname(self):
		"""Deterministic name = hash(recommendation) — one CRM Sales Action per
		CRM Recommendation (Requirement: one row per accepted/modified
		recommendation). A double-fire of the accept-decision wiring (e.g. a
		retried write) fails on the duplicate primary key instead of silently
		creating a second action row for the same recommendation.
		"""
		if not self.recommendation:
			frappe.throw(_("CRM Sales Action requires a recommendation before it can be named"))
		digest = hashlib.sha256(self.recommendation.encode("utf-8")).hexdigest()[:24]
		self.name = f"SA-{digest}"


def _crm_staff_campus(user: str) -> tuple[str | None, str | None]:
	"""Return (crm_staff_name, campus) for `user`, or (None, None) if unmapped."""
	crm_staff_name = frappe.db.get_value("CRM Staff", {"user": user}, "name")
	if not crm_staff_name:
		return None, None
	campus = frappe.db.get_value("CRM Staff", crm_staff_name, "campus")
	return crm_staff_name, campus


def on_execution_or_outcome_change(doc, method=None):
	"""Sales just recorded `business_outcome` in the Frappe UI (a plain write
	on this row) — tell crm-agents in the background so it can fire the
	closed-loop re-evaluation for this student. Detects the actual
	transition via `get_doc_before_save()`, same convention as
	crm_recommendation.on_status_decided; bypassable like any Frappe hook,
	crm-agents' reconciliation sweep is the backstop, not this call alone.
	"""
	before = doc.get_doc_before_save()
	previous_outcome = before.business_outcome if before else None
	if not doc.business_outcome or doc.business_outcome == previous_outcome:
		return
	from crm.api.agent_events import record_agent_event

	record_agent_event("sales_action.outcome_recorded.v1", doc)


def get_permission_query_conditions(user=None):
	"""LIST-view guard: only rows for students whose assigned_to falls in the
	requesting user's own campus are visible — mirrors
	crm_recommendation.get_permission_query_conditions's campus-based
	filtering."""
	if not user:
		user = frappe.session.user

	if "System Manager" in frappe.get_roles(user) or "CRM Manager" in frappe.get_roles(user):
		return None

	_crm_staff_name, campus = _crm_staff_campus(user)
	if not campus:
		return "1=0"

	crm_staff_in_campus = frappe.db.get_all(
		"CRM Staff",
		filters={"campus": campus},
		pluck="name",
	)
	if not crm_staff_in_campus:
		return "1=0"

	escaped = ", ".join(frappe.db.escape(s) for s in crm_staff_in_campus)
	return (
		"`tabCRM Sales Action`.student in ("
		"select `tabCRM Student`.name from `tabCRM Student` "
		f"where `tabCRM Student`.assigned_to in ({escaped})"
		")"
	)


def has_permission(doc, user=None, permission_type=None):
	"""Direct-GET-by-name guard — mirrors crm_recommendation.has_permission."""
	if not user:
		user = frappe.session.user

	if "System Manager" in frappe.get_roles(user) or "CRM Manager" in frappe.get_roles(user):
		return True

	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False

	_crm_staff_name, campus = _crm_staff_campus(user)
	if not campus:
		return False

	assigned_to = frappe.db.get_value("CRM Student", student, "assigned_to")
	if not assigned_to:
		return False

	assigned_campus = frappe.db.get_value("CRM Staff", assigned_to, "campus")
	return assigned_campus == campus
