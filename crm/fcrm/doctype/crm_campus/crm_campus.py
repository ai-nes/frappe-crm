# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMCampus(Document):
	def before_insert(self):
		from crm.fcrm.master_data_governance import set_governance_defaults

		set_governance_defaults(self)
