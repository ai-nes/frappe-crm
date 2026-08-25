from frappe.model.document import Document


class CRMStudentContextChange(Document):
	"""Append-only global material-context journal row."""

	def validate(self):
		if self.is_new() and not self.global_sequence:
			self.global_sequence = 0
