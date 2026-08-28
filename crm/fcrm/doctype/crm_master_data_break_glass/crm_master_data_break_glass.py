"""Immutable two-person break-glass authorization evidence."""

import frappe
from frappe.model.document import Document


class CRMMasterDataBreakGlass(Document):
	def before_insert(self):
		if not frappe.flags.get("crm_break_glass_insert"):
			frappe.throw("Break-glass requests may only be created through the governance command.", frappe.PermissionError)
		self.initiated_by = self.initiated_by or frappe.session.user

	def validate(self):
		if not self.target_doctype or not self.target_docname or not self.action or not self.nonce_hash:
			frappe.throw("Break-glass evidence is incomplete.", frappe.ValidationError)

	def on_update(self):
		if not frappe.flags.get("crm_break_glass_update"):
			frappe.throw("Break-glass evidence is immutable.", frappe.PermissionError)

	def on_trash(self):
		if getattr(frappe.flags, "in_test", False):
			return
		frappe.throw("Break-glass evidence is immutable.", frappe.PermissionError)
