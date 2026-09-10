import frappe
from frappe.model.document import Document


RULE_KINDS = {"positive", "negative", "time_decay"}


class CRMScoreRule(Document):
	def validate(self):
		if self.rule_kind not in RULE_KINDS:
			frappe.throw("Invalid score rule kind")
		if self.rule_kind != "time_decay" and not self.signal:
			frappe.throw("Positive and negative score rules require a signal")
