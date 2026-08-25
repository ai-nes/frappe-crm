import frappe
from frappe.model.document import Document
from crm.fcrm.record_retention import technical_retention_until


class CRMStudentCommandReceipt(Document):
	"""Durable command receipt; request identity cannot be rewritten."""

	_IMMUTABLE_FIELDS = (
		"command_kind",
		"command_key",
		"request_fingerprint",
		"actor",
		"request_received_at",
	)

	def validate(self):
		if self.outcome in {"attached", "created", "review_required", "review_applied", "applied", "rejected", "failed"} and not self.retention_until:
			self.retention_until = technical_retention_until("receipt")
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in self._IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"{fieldname} is immutable on a Student Command Receipt")

	def on_trash(self):
		frappe.throw("Student Command Receipts are append-only")
