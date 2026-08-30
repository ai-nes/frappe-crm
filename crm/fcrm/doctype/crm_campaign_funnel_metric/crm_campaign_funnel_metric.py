import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.legacy_fact_guard import reject_legacy_fact_write


class CRMCampaignFunnelMetric(Document):
	def before_validate(self):
		reject_legacy_fact_write("CRM Campaign Funnel Metric")

	def validate(self):
		if int(self.stage_order or 0) < 0 or int(self.numerator or 0) < 0 or int(self.denominator or 0) < 0:
			frappe.throw(_("Funnel orders and counts cannot be negative."), frappe.ValidationError)
		if int(self.numerator or 0) > int(self.denominator or 0):
			frappe.throw(_("Funnel numerator cannot exceed denominator."), frappe.ValidationError)
