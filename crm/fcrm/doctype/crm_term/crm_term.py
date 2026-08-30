import frappe
from frappe.model.document import Document


class CRMTerm(Document):
	def autoname(self):
		candidate = (self.term_name or "").strip()
		# Enrollment Status is surfaced directly throughout admissions Desk forms.
		# Reserve its human-readable document names; colliding shared-catalogue
		# terms keep a category prefix instead.
		if self.category != "enrollment_status" and frappe.db.exists(
			"CRM Term", {"term_name": candidate, "category": "enrollment_status"}
		):
			self.name = f"{self.category}:{candidate}"
			return
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
