import frappe
from frappe.model.document import Document


class CRMRecommendationFeedback(Document):
	"""Immutable learning signal attached to one Recommendation/Outcome pair."""

	def validate(self):
		if not getattr(frappe.flags, "nba_service_write", False):
			frappe.throw("Recommendation Feedback is managed by the feedback service.", frappe.PermissionError)
		if self.get_doc_before_save():
			frappe.throw("Recommendation Feedback is immutable.", frappe.PermissionError)
		if not 0 <= float(self.predicted_probability) <= 1:
			frappe.throw("Predicted probability must be between 0 and 1.", frappe.ValidationError)
		for field in ("reward", "actual_impact"):
			value = self.get(field)
			if value not in (None, "") and not -1 <= float(value) <= 1:
				frappe.throw(f"{field} must be between -1 and 1.", frappe.ValidationError)

	def on_trash(self):
			frappe.throw("Recommendation Feedback cannot be deleted.", frappe.PermissionError)
