import frappe
from frappe import _
from frappe.model.document import Document


class CRMScholarshipPolicy(Document):
	def validate(self):
		if not 0 <= float(self.percentage or 0) <= 100:
			frappe.throw(_("Scholarship percentage must be between 0 and 100."), frappe.ValidationError)
		if float(self.amount or 0) < 0:
			frappe.throw(_("Scholarship amount cannot be negative."), frappe.ValidationError)
		if self.effective_until and self.effective_from > self.effective_until:
			frappe.throw(_("Effective From must not be after Effective Until."), frappe.ValidationError)
