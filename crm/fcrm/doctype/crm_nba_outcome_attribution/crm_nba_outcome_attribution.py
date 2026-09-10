import frappe
from frappe.model.document import Document


class CRMNBAOutcomeAttribution(Document):
	"""Append-only causal attribution row for governed NBA calibration."""

	def validate(self):
		if not getattr(frappe.flags, "nba_calibration_write", False):
			frappe.throw("NBA outcome attribution is managed by the calibration service.", frappe.PermissionError)
		if self.get_doc_before_save():
			frappe.throw("NBA outcome attribution is immutable.", frappe.PermissionError)
		required = (
			"evaluation", "recommendation", "action_execution", "terminal_result_revision",
			"cohort_key", "season", "observation_start", "observation_end", "attribution_rule",
		)
		missing = [field for field in required if not self.get(field)]
		if missing:
			frappe.throw(f"Attribution is missing: {', '.join(missing)}", frappe.ValidationError)

	def on_trash(self):
		frappe.throw("NBA outcome attribution cannot be deleted.", frappe.PermissionError)
