import frappe
from frappe.model.document import Document

_DIRECTIONS = {"rising", "falling", "stable", "changed"}


class CRMIntentTrajectory(Document):
	"""Latest deterministic intent-evolution snapshot for one student.

	One row per student (append is a rewrite of the same row); prior snapshots
	live in Frappe document version history. Written only by the AI service
	boundary, never from chat.
	"""

	def validate(self):
		if not self.student:
			frappe.throw("Intent trajectory requires a student.", frappe.ValidationError)
		if self.direction and self.direction not in _DIRECTIONS:
			frappe.throw("Intent trajectory direction is invalid.", frappe.ValidationError)
		# strength is a normalised share -> clamp; slope is a raw regression
		# coefficient over stage indices and is stored as produced.
		if self.strength is not None:
			try:
				self.strength = max(0.0, min(1.0, float(self.strength)))
			except (TypeError, ValueError):
				frappe.throw("Intent trajectory strength must be numeric.", frappe.ValidationError)
		self.model_free = 1
