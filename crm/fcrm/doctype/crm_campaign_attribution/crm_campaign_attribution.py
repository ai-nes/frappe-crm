import frappe
from frappe import _
from frappe.model.document import Document


class CRMCampaignAttribution(Document):
	def validate(self):
		if not 0 <= float(self.weight or 0) <= 1:
			frappe.throw(_("Attribution weight must be between 0 and 1."), frappe.ValidationError)
		if not 0 <= float(self.confidence or 0) <= 100:
			frappe.throw(_("Attribution confidence must be between 0 and 100."), frappe.ValidationError)
