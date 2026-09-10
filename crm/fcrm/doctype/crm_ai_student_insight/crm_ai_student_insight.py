import frappe
from frappe.model.document import Document


class CRMAIStudentInsight(Document):
	def before_insert(self):
		if not self.generated_at:
			self.generated_at = frappe.utils.now_datetime()
