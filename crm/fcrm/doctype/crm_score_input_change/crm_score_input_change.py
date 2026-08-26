from frappe.model.document import Document


class CRMScoreInputChange(Document):
	"""Append-only global journal of score_input_revision bumps -- the
	reconciliation replay source for the scoring event consumer, mirroring
	CRM Student Context Change."""

	def validate(self):
		if self.is_new() and not self.global_sequence:
			self.global_sequence = 0
