import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class CRMAdmissionYear(Document):
	def validate(self):
		if self.start_date and self.end_date and getdate(self.start_date) > getdate(self.end_date):
			frappe.throw(_("Admission Year start date must be before its end date."), frappe.ValidationError)
		if self.is_active and frappe.db.exists(
			"CRM Admission Year", {"is_active": 1, "name": ["!=", self.name]}
		):
			frappe.throw(
				_("Only one Admission Year can be active at a time. Deactivate the current year first."),
				frappe.DuplicateEntryError,
			)
