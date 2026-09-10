"""Immutable individual governance approval evidence."""

import frappe
from frappe.model.document import Document


class CRMMasterDataChangeApproval(Document):
	def before_insert(self):
		if not frappe.flags.get("crm_governance_approval_insert"):
			frappe.throw("Approvals may only be recorded through the governance command.", frappe.PermissionError)
		self.approved_by = frappe.session.user
		self.approval_key = f"{self.parent}:{self.approval_role}"

	def validate(self):
		if not self.parent or not self.approval_role or not self.approved_by:
			frappe.throw("Approval evidence requires a change, role and actor.")

	def on_update(self):
		if not (frappe.flags.get("crm_governance_approval_insert") or frappe.flags.get("crm_governance_log_update")):
			frappe.throw("Approval evidence is immutable.", frappe.PermissionError)

	def on_trash(self):
		if frappe.flags.in_test:
			return
		frappe.throw("Approval evidence is immutable.", frappe.PermissionError)
