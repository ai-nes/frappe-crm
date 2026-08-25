import hashlib
from typing import ClassVar

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.permissions import (
	get_permission_query_conditions as get_student_permission_query_conditions,
)


class CRMSalesAction(Document):
	_V2_PROTECTED_FIELDS: ClassVar[frozenset[str]] = frozenset({
		"student_task",
		"action_type",
		"action_revision",
		"package_revision",
		"requires_review",
		"execution_package",
		"execution_status",
		"business_outcome",
	})

	def validate(self):
		before = self.get_doc_before_save()
		if before and self.student_task and not getattr(frappe.flags, "student_task_command", False):
			for field in self._V2_PROTECTED_FIELDS:
				if before.get(field) != self.get(field):
					frappe.throw(
						frappe._("v2 Sales Action fields can only be changed through controlled commands."),
						frappe.PermissionError,
					)

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
		prefix = "SA-E2E-FPT-2026-" if self.recommendation.startswith("REC-E2E-FPT-2026-") else "SA-"
		self.name = f"{prefix}{digest}"


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
	if doc.student_task:
		from crm.services.student_context import mark_student_context_changed

		mark_student_context_changed(doc.student, "sales_action_outcome")


def get_permission_query_conditions(user=None):
	"""LIST-view guard derived from the canonical CRM Student scope."""
	if not user:
		user = frappe.session.user

	student_condition = get_student_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	return (
		"`tabCRM Sales Action`.student in ("
		"select `tabCRM Student`.name from `tabCRM Student` "
		f"where {student_condition}"
		")"
	)


def has_permission(doc, user=None, permission_type=None):
	"""Direct-GET-by-name guard using the same Student scope as list views."""
	if not user:
		user = frappe.session.user

	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False

	student_condition = get_student_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return True
	return bool(
		frappe.db.sql(
			"select name from `tabCRM Student` where name = %s and (" + student_condition + ") limit 1",
			(student,),
		)
	)
