import frappe
from frappe import _
from frappe.model.document import Document


class CRMSchoolContact(Document):
	def before_validate(self):
		if not getattr(frappe.flags, "school_compatibility_migration", False):
			frappe.throw(
				_("CRM School Contact is a read-only compatibility artifact; use CRM School Stakeholder."),
				frappe.PermissionError,
			)

	def validate(self):
		filters = {"high_school": self.high_school, "is_primary": 1}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if self.is_primary and frappe.db.exists("CRM School Contact", filters):
			frappe.throw(_("A high school may have only one primary contact."), frappe.DuplicateEntryError)
