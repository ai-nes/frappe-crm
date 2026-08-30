from frappe.model.document import Document

from crm.fcrm.legacy_fact_guard import reject_legacy_fact_write


class CRMCampaignPerformanceDimension(Document):
	def before_validate(self):
		reject_legacy_fact_write("CRM Campaign Performance Dimension")
