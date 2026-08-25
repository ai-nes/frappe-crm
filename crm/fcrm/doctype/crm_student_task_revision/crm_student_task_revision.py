from frappe.model.document import Document


class CRMStudentTaskRevision(Document):
	"""Immutable generated/edited execution package revision."""

	def validate(self):
		if not self.task or not self.revision:
			raise ValueError("task and revision are required")
