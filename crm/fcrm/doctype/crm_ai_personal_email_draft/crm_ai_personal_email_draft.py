import frappe
from frappe.model.document import Document


class CRMAIPersonalEmailDraft(Document):
	def before_insert(self):
		if not self.generated_by:
			self.generated_by = frappe.session.user
		if not self.generated_at:
			self.generated_at = frappe.utils.now_datetime()
