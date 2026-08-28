import hashlib

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.permissions import (
	get_permission_query_conditions as get_student_permission_query_conditions,
	has_permission as has_student_permission,
)


class CRMSalesAction(Document):
	"""Durable execution aggregate; lifecycle writes belong to Phase 6 commands."""

	_IMMUTABLE_FIELDS = (
		"recommendation", "student_task", "student", "action_type", "created_at", "due_at",
		"assignee_snapshot", "correlation_id", "idempotency_key",
	)
	_ALLOWED_TRANSITIONS = {
		"planned": {"in_progress", "cancelled"},
		"in_progress": {"completed", "failed", "cancelled"},
	}
	_OUTCOME_CODES = {
		"NO_RESPONSE", "INTEREST_INCREASED", "NEEDS_MORE_INFORMATION", "CALL_BACK_LATER",
		"APPLICATION_STARTED", "APPLICATION_COMPLETED", "NOT_INTERESTED",
	}

	def _from_command(self):
		return bool(getattr(self.flags, "from_phase6_command", False) or getattr(self.flags, "phase6_break_glass", False))

	def autoname(self):
		"""Deterministic name = hash(recommendation or student_task) — one CRM
		Sales Action per correlated aggregate. A double-fire of the
		accept-decision wiring (e.g. a retried write) fails on the duplicate
		primary key instead of silently creating a second action row.
		"""
		key = self.recommendation or self.student_task
		if not key:
			frappe.throw(_("CRM Sales Action requires a recommendation or student_task before it can be named"))
		digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]
		prefix = "SA-E2E-FPT-2026-" if key.startswith("REC-E2E-FPT-2026-") else "SA-"
		self.name = f"{prefix}{digest}"

	def validate(self):
		before = self.get_doc_before_save()
		if self.is_new():
			if not self._from_command():
				frappe.throw(_("CRM Sales Actions may only be created by a Phase 6 server command."))
			if not self.due_at or not self.assignee_staff:
				frappe.throw(_("CRM Sales Action requires due_at and assignee_staff."))
			if self.recommendation:
				source_student = frappe.db.get_value("CRM Recommendation", self.recommendation, "student")
			elif self.student_task:
				source_student = frappe.db.get_value("CRM Student Task", self.student_task, "student")
			else:
				frappe.throw(_("CRM Sales Action requires a recommendation or student_task."))
			if source_student != self.student:
				frappe.throw(_("CRM Sales Action must use its source aggregate's Student."))
			return
		if not before:
			return

		changed = {field for field in self._IMMUTABLE_FIELDS if self.get(field) != before.get(field)}
		if changed:
			frappe.throw(_("CRM Sales Action fields are immutable: {0}").format(", ".join(changed)))
		lifecycle_fields = (
			"assignee_staff", "assignment_revision",
			"assignment_history",
			"execution_status", "started_at", "completed_at", "outcome_code", "business_outcome",
			"outcome_notes", "outcome_evidence", "outcome_at", "outcome_actor", "linked_interaction",
			"terminal_reason", "action_revision", "supersedes_decision_event",
		)
		if any(self.get(field) != before.get(field) for field in lifecycle_fields) and not self._from_command():
			frappe.throw(_("CRM Sales Action lifecycle changes must use a Phase 6 server command."))
		if before.execution_status != self.execution_status:
			allowed = self._ALLOWED_TRANSITIONS.get(before.execution_status, set())
			if self.execution_status not in allowed:
				frappe.throw(_("Illegal CRM Sales Action transition: {0} -> {1}").format(
					before.execution_status, self.execution_status
				))
		if self.assignee_staff != before.assignee_staff and self.execution_status in {"completed", "failed", "cancelled"}:
			frappe.throw(_("Terminal CRM Sales Actions cannot be reassigned."))
		if self.execution_status == "completed":
			self._validate_completed()
		elif self.execution_status in {"failed", "cancelled"} and not self.terminal_reason:
			frappe.throw(_("A terminal reason is required when failing or cancelling a CRM Sales Action."))

	def _validate_completed(self):
		outcome_code = self.outcome_code or self.business_outcome
		if outcome_code not in self._OUTCOME_CODES:
			frappe.throw(_("Completed CRM Sales Actions require an allowlisted outcome code."))
		if not self.completed_at or not self.outcome_at or not self.outcome_actor:
			frappe.throw(_("Completed CRM Sales Actions require completed_at, outcome_at and outcome_actor."))
		if not self.linked_interaction:
			return
		interaction_student = frappe.db.get_value("CRM Interaction", self.linked_interaction, "student")
		if interaction_student != self.student:
			frappe.throw(_("Linked CRM Interaction must belong to the same Student as the CRM Sales Action."))
		if not frappe.db.exists(
			"CRM Student Outcome",
			{"student": self.student, "interaction": self.linked_interaction},
		):
			frappe.throw(_("Linked CRM Interaction requires a Phase 5 Student Outcome."))


def get_permission_query_conditions(user=None):
	"""Project the canonical CRM Student own/team/director scope onto actions."""
	if not user:
		user = frappe.session.user
	student_condition = get_student_permission_query_conditions("CRM Student", user=user)
	if student_condition is None:
		return None
	if student_condition == "1=0":
		return "1=0"
	return (
		"`tabCRM Sales Action`.student in ("
		"select `tabCRM Student`.name from `tabCRM Student` "
		f"where ({student_condition})"
		")"
	)


def has_permission(doc, user=None, permission_type=None):
	"""Direct-GET-by-name guard using the same current Student scope."""
	if not user:
		user = frappe.session.user

	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False

	try:
		student_doc = frappe.get_doc("CRM Student", student)
		return has_student_permission(student_doc, user=user, permission_type=permission_type)
	except Exception:
		return False
