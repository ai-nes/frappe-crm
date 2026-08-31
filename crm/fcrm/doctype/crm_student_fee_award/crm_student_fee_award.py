import frappe
from frappe import _
from frappe.model.document import Document


class CRMStudentFeeAward(Document):
	def validate(self):
		if float(self.amount or 0) < 0 or not 0 <= float(self.percentage or 0) <= 100:
			frappe.throw(_("Fee award amount or percentage is invalid."), frappe.ValidationError)
