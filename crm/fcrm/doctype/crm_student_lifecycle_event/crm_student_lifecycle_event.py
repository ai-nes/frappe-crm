import frappe
from frappe.model.document import Document


class CRMStudentLifecycleEvent(Document):
	"""Immutable authoritative lifecycle transition event."""

	_IMMUTABLE_FIELDS = (
		"event_id", "student", "from_stage", "to_stage", "transition_kind", "prior_active_stage",
		"reason", "evidence_references", "actor", "actor_scope", "occurred_at", "command_receipt",
		"idempotency_key", "correlation_id", "policy_version", "schema_version", "supersedes",
	)

	def validate(self):
		if self.transition_kind and self.transition_kind not in {"forward", "lost", "reopen", "override"}:
			frappe.throw("Unsupported Student lifecycle transition kind")
		if self.to_stage and self.to_stage not in {"Lead", "MQL", "Applicant", "Enrolled", "Lost"}:
			frappe.throw("Unsupported Student lifecycle stage")
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in self._IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"{fieldname} is immutable on a Student Lifecycle Event")

	def on_trash(self):
		frappe.throw("Student Lifecycle Events are append-only")
