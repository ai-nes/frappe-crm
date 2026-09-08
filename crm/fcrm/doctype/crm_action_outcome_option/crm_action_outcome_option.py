import frappe
from frappe.model.document import Document

from crm.services.action_outcome import DIMENSION_REDUCERS


class CRMActionOutcomeOption(Document):
	"""One (action, outcome_code, dimension) Decision Effect row.

	Read-only projection of ``crm.services.action_outcome`` for admin
	visibility/audit; the Python registry is the source of truth business
	logic reads, not this doctype.
	"""

	def validate(self):
		if self.dimension not in DIMENSION_REDUCERS:
			frappe.throw(f"Unknown decision effect dimension: {self.dimension}", frappe.ValidationError)
