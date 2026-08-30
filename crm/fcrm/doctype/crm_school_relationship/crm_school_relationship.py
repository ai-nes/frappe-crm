import frappe
from frappe import _
from frappe.model.document import Document


class CRMSchoolRelationship(Document):
	def before_validate(self):
		if not getattr(frappe.flags, "school_compatibility_migration", False):
			frappe.throw(
				_(
					"CRM School Relationship is a read-only compatibility artifact; use CRM School Stakeholder."
				),
				frappe.PermissionError,
			)

	def validate(self):
		if not 0 <= float(self.relationship_score or 0) <= 100:
			frappe.throw(_("Relationship Score must be between 0 and 100."), frappe.ValidationError)
		filters = {"high_school": self.high_school, "is_primary": 1}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if self.is_primary and frappe.db.exists("CRM School Relationship", filters):
			frappe.throw(
				_("A high school may have only one primary relationship."), frappe.DuplicateEntryError
			)
