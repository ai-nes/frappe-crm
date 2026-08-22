import frappe
from frappe.model.document import Document


class CRMMasterDataChangeLog(Document):
	def validate(self):
		from crm.fcrm.master_data_governance import GOVERNED_DOCTYPES

		if self.reference_doctype not in GOVERNED_DOCTYPES:
			frappe.throw(f"{self.reference_doctype} is not a governed master data type")
