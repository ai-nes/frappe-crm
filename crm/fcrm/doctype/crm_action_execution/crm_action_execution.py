import frappe
from frappe.model.document import Document

TRANSITIONS = {
	"pending": {"queued", "in_progress", "failed", "cancelled"},
	"queued": {"in_progress", "failed", "cancelled"},
	"in_progress": {"completed", "failed", "cancelled"},
	"completed": set(),
	"failed": set(),
	"cancelled": set(),
}


class CRMActionExecution(Document):
	"""Provider execution projection; all mutations come from server commands."""

	def validate(self):
		if not getattr(frappe.flags, "nba_service_write", False):
			frappe.throw("Action Execution is managed by the execution service.", frappe.PermissionError)
		before = self.get_doc_before_save()
		if (
			before
			and before.status != self.status
			and self.status not in TRANSITIONS.get(before.status, set())
		):
			frappe.throw("Invalid Action Execution transition.", frappe.ValidationError)
