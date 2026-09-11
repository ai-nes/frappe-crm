"""Guard the authoritative active-rule pointer from direct edits."""

import frappe
from frappe.model.document import Document


class CRMRuleSettings(Document):
	def validate(self):
		if not getattr(frappe.flags, "crm_rule_settings_lifecycle", False):
			frappe.throw("CRM Rule Settings pointer can only change through activate_rule_version.", frappe.PermissionError)
		try:
			revision = int(self.pointer_revision or 0)
		except (TypeError, ValueError):
			frappe.throw("CRM Rule Settings pointer_revision must be a non-negative integer.", frappe.ValidationError)
		if revision < 0:
			frappe.throw("CRM Rule Settings pointer_revision must be a non-negative integer.", frappe.ValidationError)
		if self.active_ruleset_digest and len(str(self.active_ruleset_digest)) != 64:
			frappe.throw("CRM Rule Settings active_ruleset_digest must be a SHA-256 digest.", frappe.ValidationError)

	def on_trash(self):
		frappe.throw("CRM Rule Settings is a required singleton and cannot be deleted.", frappe.PermissionError)
