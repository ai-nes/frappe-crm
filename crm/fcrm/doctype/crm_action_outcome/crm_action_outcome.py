import frappe
from frappe.model.document import Document


class CRMActionOutcome(Document):
	"""Immutable outcome evidence for one action execution."""

	def validate(self):
		if not getattr(frappe.flags, "nba_service_write", False):
			frappe.throw("Action Outcome is managed by the outcome service.", frappe.PermissionError)
		if self.get_doc_before_save():
			frappe.throw("Action Outcome is immutable.", frappe.PermissionError)
		if self.impact_score not in (None, "") and not -1 <= float(self.impact_score) <= 1:
			frappe.throw("Impact score must be between -1 and 1.", frappe.ValidationError)

	def on_trash(self):
			frappe.throw("Action Outcome cannot be deleted.", frappe.PermissionError)
