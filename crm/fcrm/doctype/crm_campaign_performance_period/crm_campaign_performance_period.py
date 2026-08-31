import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.legacy_fact_guard import reject_legacy_fact_write


class CRMCampaignPerformancePeriod(Document):
	def before_validate(self):
		reject_legacy_fact_write("CRM Campaign Performance Period")

	def validate(self):
		if self.period_start > self.period_end:
			frappe.throw(_("Period Start must not be after Period End."), frappe.ValidationError)
		for fieldname in ("spend", "impressions", "clicks", "leads", "applications", "enrolled", "recognized_revenue"):
			if float(self.get(fieldname) or 0) < 0:
				frappe.throw(_("{0} cannot be negative.").format(fieldname), frappe.ValidationError)
