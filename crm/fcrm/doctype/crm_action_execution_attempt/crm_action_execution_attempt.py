from frappe.model.document import Document


class CRMActionExecutionAttempt(Document):
	"""Immutable identity and state fence for one governed Action attempt."""

	def before_insert(self):
		self.provider_idempotency_key = self.provider_idempotency_key or self.name
