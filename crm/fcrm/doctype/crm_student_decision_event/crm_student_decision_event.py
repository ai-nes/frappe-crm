import frappe
from frappe.model.document import Document


class CRMStudentDecisionEvent(Document):
	"""Append-only audit envelope for Phase 6 decisions and action transitions."""

	_IMMUTABLE_FIELDS = (
		"event_id", "event_type", "decision_operation", "student", "recommendation", "action",
		"action_definition_revision", "action_definition_digest", "manual_override",
		"command_receipt", "aggregate_revision", "from_state", "to_state", "delta", "actor", "actor_scope",
		"occurred_at", "reason", "correlation_id", "idempotency_key", "policy_version",
		"schema_version", "supersedes",
	)
	_EVENT_TYPES = {
		"recommendation_decided", "task_decided", "action_started", "action_completed", "action_failed",
		"action_cancelled", "action_reassigned", "action_superseded",
	}
	_DECISION_OPERATIONS = {"ACCEPT", "ACCEPT_WITH_CHANGES", "REJECT", "DEFER", "DISMISS"}

	def validate(self):
		if self.event_type not in self._EVENT_TYPES:
			frappe.throw("Unsupported Student decision event type")
		if self.decision_operation and self.decision_operation not in self._DECISION_OPERATIONS:
			frappe.throw("Unsupported Student decision operation")
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in self._IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"{fieldname} is immutable on a Student Decision Event")

	def on_trash(self):
		frappe.throw("Student Decision Events are append-only")
