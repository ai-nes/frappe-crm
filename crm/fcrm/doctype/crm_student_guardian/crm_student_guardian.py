import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.student_reference import canonical_student


class CRMStudentGuardian(Document):
	def before_validate(self):
		self.student = canonical_student(self.student) or self.student

	def validate(self):
		if not self.student or not frappe.db.exists("CRM Student", self.student):
			frappe.throw(
				_("A valid Student is required for a guardian relationship."), frappe.ValidationError
			)
		if self.related_student and not frappe.db.exists("CRM Student", self.related_student):
			frappe.throw(_("The related sibling Student does not exist."), frappe.ValidationError)
