import frappe
from frappe.model.document import Document


class CRMScoreTemplate(Document):
	def validate(self):
		if self.status == "Active":
			existing = frappe.db.get_value(
				"CRM Score Template",
				{"status": "Active", "name": ("!=", self.name)},
				"name",
			)
			if existing:
				frappe.throw(
					f"Only one Score Template can be Active at a time. Please deactivate <b>{existing}</b> first."
				)
