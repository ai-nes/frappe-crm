import frappe
from frappe.model.document import Document


class CRMStudentOwnershipEvent(Document):
	"""Append-only, allowlisted ownership history."""

	_IMMUTABLE_FIELDS = (
		"event_type",
		"student",
		"aggregate_revision",
		"actor",
		"scope_snapshot",
		"policy_version",
		"schema_version",
		"command_receipt",
		"idempotency_key",
		"source_key",
		"correlation_token",
		"before_state",
		"after_state",
		"event_at",
		"reason",
		"reason_sensitivity",
	)

	def validate(self):
		if self.event_type and self.event_type not in {
			"assigned",
			"reassigned",
			"released",
			"pool_assigned",
			"owner_assigned",
			"superseded",
		}:
			frappe.throw("Unsupported Student ownership event type")
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in self._IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"{fieldname} is immutable on a Student Ownership Event")

	def on_trash(self):
		frappe.throw("Student Ownership Events are append-only")
