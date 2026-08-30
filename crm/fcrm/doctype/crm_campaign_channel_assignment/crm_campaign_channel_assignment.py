import frappe
from frappe import _
from frappe.model.document import Document


class CRMCampaignChannelAssignment(Document):
	def validate(self):
		if self.effective_until and self.effective_from > self.effective_until:
			frappe.throw(_("Effective From must not be after Effective Until."), frappe.ValidationError)
