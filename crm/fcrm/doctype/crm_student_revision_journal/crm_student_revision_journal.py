import frappe
from frappe.model.document import Document


class CRMStudentRevisionJournal(Document):
	IMMUTABLE_FIELDS = {
		"event_id", "student", "event_type", "stream", "revision", "stream_sequence", "reason", "actor",
		"actor_scope", "occurred_at", "idempotency_key", "correlation_id", "policy_version", "schema_version", "payload",
	}

	def validate(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			frappe.throw("Revision journal history is unavailable.")
		for fieldname in self.IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw("Student revision journal entries are append-only.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Student revision journal entries are append-only.", frappe.PermissionError)
