import frappe
from frappe.model.document import Document


class CRMAILeadInsightItem(Document):
	def validate(self):
		if self.item_kind not in {"interest", "objection", "risk"}:
			frappe.throw("Invalid AI insight item kind")

