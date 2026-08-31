import frappe
from frappe import _
from frappe.model.document import Document


class CRMFeePolicy(Document):
	def validate(self):
		if float(self.amount or 0) < 0:
			frappe.throw(_("Fee amount cannot be negative."), frappe.ValidationError)
		if self.effective_until and self.effective_from > self.effective_until:
			frappe.throw(_("Effective From must not be after Effective Until."), frappe.ValidationError)
