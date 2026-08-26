import frappe
from frappe.model.document import Document


class CRMStudentOutcome(Document):
	"""Immutable canonical Student outcome event."""

	_IMMUTABLE_FIELDS = (
		"event_id", "student", "interaction", "outcome_code", "continuity_kind",
		"next_action", "next_action_assignee", "next_action_due_at", "continuity_reason",
		"continuity_expires_at", "qualification_evidence", "source_doctype", "source_name",
		"source_key", "actor", "actor_scope", "occurred_at", "supersedes", "command_receipt",
		"idempotency_key", "correlation_id", "policy_version", "schema_version",
	)

	def validate(self):
		if self.outcome_code and self.outcome_code not in {
			"connected", "qualified", "follow_up_required", "no_response", "not_interested", "invalid", "completed"
		}:
			frappe.throw("Unsupported Student outcome code")
		if self.continuity_kind and self.continuity_kind not in {"task", "waiting", "terminal"}:
			frappe.throw("Unsupported Student outcome continuity")
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in self._IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"{fieldname} is immutable on a Student Outcome")

	def on_trash(self):
		frappe.throw("Student Outcomes are append-only")
