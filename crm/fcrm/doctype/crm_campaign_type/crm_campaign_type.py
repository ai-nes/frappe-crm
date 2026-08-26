from frappe.model.document import Document


class CRMCampaignType(Document):
	def before_insert(self):
		from crm.fcrm.master_data_governance import set_governance_defaults

		set_governance_defaults(self)
