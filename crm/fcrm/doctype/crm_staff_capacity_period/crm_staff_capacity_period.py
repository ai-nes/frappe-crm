import frappe
from frappe import _
from frappe.model.document import Document


class CRMStaffCapacityPeriod(Document):
	def validate(self):
		if self.period_start > self.period_end:
			frappe.throw(_("Period Start must not be after Period End."))
		if int(self.capacity_units or 0) < 0 or int(self.max_active_students or 0) < 0:
			frappe.throw(_("Capacity values cannot be negative."))
