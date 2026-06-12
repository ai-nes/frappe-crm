from frappe.model.document import Document

# Maps to CRM Score History Detail.category values: Fit, Intent, Engagement
# CRM Time Decay Config rows → category: Time Decay
# CRM Negative Score Rule rows → category: Negative


class CRMScoreRule(Document):
	pass
