import frappe
from frappe.model.document import Document

from crm.fcrm.student_policy import validate_policy_publication


class CRMStudentRoutingPolicy(Document):
	"""A versioned routing policy; active versions are immutable."""

	_LOCKED_FIELDS = (
		"policy_key", "policy_version", "campus", "student_pool", "strategy",
		"effective_from", "effective_until", "recipient_scope", "approved_by",
		"approved_at", "break_glass_reason",
	)

	def validate(self):
		if self.strategy and self.strategy != "round_robin":
			frappe.throw("Unsupported Student routing strategy")
		validate_policy_publication(self, self._LOCKED_FIELDS)

	def on_trash(self):
		frappe.throw("Student Routing Policies are retained for audit")
