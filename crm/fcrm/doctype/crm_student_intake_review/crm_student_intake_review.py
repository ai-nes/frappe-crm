import frappe
from frappe.model.document import Document


class CRMStudentIntakeReview(Document):
	"""Review decisions are evidence, not a generic merge or reassignment UI."""

	def on_trash(self):
		frappe.throw("Student intake reviews are retained as audit evidence")
