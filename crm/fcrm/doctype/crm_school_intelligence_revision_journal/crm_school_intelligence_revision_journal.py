import frappe
from frappe.model.document import Document


class CRMSchoolIntelligenceRevisionJournal(Document):
	def validate(self):
		if self.is_new():
			return
		frappe.throw("School intelligence revision journal entries are append-only.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("School intelligence revision journal entries are append-only.", frappe.PermissionError)
