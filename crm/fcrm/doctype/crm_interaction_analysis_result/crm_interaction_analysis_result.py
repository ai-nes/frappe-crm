import frappe
from frappe.model.document import Document


class CRMInteractionAnalysisResult(Document):
	"""Immutable, evidence-referenced settlement history for one run revision."""

	def validate(self):
		if not self.analysis_run or self.state not in {"no_intent", "intent_bearing", "unknown", "failed"}:
			frappe.throw("Interaction analysis result identity is invalid.")
		if len(self.source_digest or "") != 64 or int(self.source_revision or 0) < 1:
			frappe.throw("Interaction analysis result source revision is invalid.")
		if not self.is_new():
			frappe.throw("Interaction analysis results are immutable.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Interaction analysis results are immutable.", frappe.PermissionError)
