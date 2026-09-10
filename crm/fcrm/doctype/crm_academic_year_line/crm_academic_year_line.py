import frappe
from frappe.model.document import Document


class CRMAcademicYearLine(Document):
	def validate(self):
		if self.line_kind not in {"tuition", "scholarship", "quota"}:
			frappe.throw("Invalid academic year line kind")

