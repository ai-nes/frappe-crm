import frappe
from frappe.model.document import Document

from crm.fcrm.analysis_runs import _validate_ruleset_identity
from crm.fcrm.decision_trace import validate_rule_decision


class CRMInteractionAnalysisResult(Document):
	"""Immutable, evidence-referenced settlement history for one run revision."""

	def validate(self):
		if not self.analysis_run or self.state not in {"no_intent", "intent_bearing", "unknown", "failed"}:
			frappe.throw("Interaction analysis result identity is invalid.")
		if len(self.source_digest or "") != 64 or int(self.source_revision or 0) < 1:
			frappe.throw("Interaction analysis result source revision is invalid.")
		_validate_ruleset_identity(self)
		if self.rule_decision:
			try:
				decision = validate_rule_decision(self.rule_decision)
			except ValueError as exc:
				frappe.throw(str(exc), frappe.ValidationError)
			if any(
				decision[field] != getattr(self, field, None)
				for field in ("rule_version", "rule_version_digest", "ruleset_digest")
			):
				frappe.throw("Interaction analysis rule decision identity is inconsistent.", frappe.ValidationError)
		if not self.is_new():
			frappe.throw("Interaction analysis results are immutable.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Interaction analysis results are immutable.", frappe.PermissionError)
