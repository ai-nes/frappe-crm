import frappe
from frappe.model.document import Document


class CRMTerm(Document):
	def autoname(self):
		candidate = (self.term_name or "").strip()
		existing_category = frappe.db.get_value("CRM Term", candidate, "category")
		self.name = candidate if not existing_category or existing_category == self.category else f"{self.category}:{candidate}"

	def validate(self):
		if not self.term_name or not self.category:
			frappe.throw("Term and category are required.")
		if self.is_new() and not self.is_active:
			frappe.throw("A new term must be active.")
		if not self.is_new() and self.has_value_changed("category"):
			frappe.throw("A term category is immutable.", frappe.PermissionError)

	def on_trash(self):
		if not frappe.flags.get("crm_term_migration") and not frappe.flags.in_test:
			frappe.throw("Terms must be retired through governance.", frappe.PermissionError)
