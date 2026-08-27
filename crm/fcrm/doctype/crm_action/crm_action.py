import frappe
from frappe.model.document import Document


class CRMAction(Document):
	"""Canonical admissions Action work item and execution evidence aggregate."""

	TERMINAL = {"completed", "cancelled", "superseded", "rejected"}
	TRANSITIONS = {
		"pending": {"accepted", "rejected", "deferred", "superseded"},
		"accepted": {"in-progress", "requires-review", "cancelled", "deferred"},
		"in-progress": {"completed", "requires-review", "cancelled"},
		"requires-review": {"accepted", "in-progress", "cancelled", "superseded"},
		"deferred": {"accepted", "superseded"},
	}

	_PROTECTED = frozenset({
		"student", "action_type", "objective", "disposition", "source_context_revision",
		"policy_context_version", "generation_idempotency_key", "producer_identity",
		"payload_digest", "evidence_references", "action_revision", "current_slot",
		"due_at", "revisit_at", "action_owner", "origin", "contact", "legacy_student_task", "legacy_generic_task",
		"execution_status", "started_at", "outcome_code", "outcome_evidence", "outcome_notes", "linked_interaction", "accepted_at", "completed_at", "terminal_reason",
		"decision_reason", "decision_actor", "decision_at", "decision_revision",
	})

	def validate(self):
		self.worklist_priority_rank = {"high": 0, "medium": 1, "low": 2}.get(self.priority, 99)
		if self.state not in self.TRANSITIONS and self.state not in self.TERMINAL:
			frappe.throw("Invalid CRM Action state.", frappe.ValidationError)
		if self.disposition == "ACT" and not self.action_type:
			frappe.throw("ACT actions require an action type.", frappe.ValidationError)
		if self.disposition != "ACT" and self.action_type:
			frappe.throw("Non-ACT actions cannot carry an action type.", frappe.ValidationError)
		before = self.get_doc_before_save()
		if before and not getattr(frappe.flags, "crm_action_command", False):
			for field in self._PROTECTED:
				if before.get(field) != self.get(field):
					frappe.throw("CRM Action fields require a controlled command.", frappe.PermissionError)
		if before and before.state != self.state and self.state not in self.TRANSITIONS.get(before.state, set()):
			frappe.throw(f"Illegal CRM Action transition: {before.state} -> {self.state}", frappe.ValidationError)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope
	user = user or frappe.session.user
	condition = student_scope("CRM Student", user=user)
	return f"`tabCRM Action`.student in (select name from `tabCRM Student` where {condition})" if condition else None


def has_permission(doc, user=None, permission_type=None):
	student = doc.get("student") if isinstance(doc, dict) else getattr(doc, "student", None)
	if not student:
		return False
	from crm.fcrm.permissions import get_permission_query_conditions as student_scope
	condition = student_scope("CRM Student", user=user or frappe.session.user)
	if condition is None:
		return True
	return bool(frappe.db.sql(
		"select name from `tabCRM Student` where name = %s and (" + condition + ") limit 1", (student,)
	))
