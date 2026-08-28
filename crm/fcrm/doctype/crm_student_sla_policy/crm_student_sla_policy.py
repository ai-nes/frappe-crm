import json

import frappe
from frappe.model.document import Document

from crm.fcrm.student_policy import validate_policy_publication


class CRMStudentSLAPolicy(Document):
	"""Versioned first-response SLA policy; an active version is locked."""

	_LOCKED_FIELDS = (
		"policy_key", "policy_version", "campus", "student_pool", "warning_minutes",
		"breach_minutes", "escalation_minutes", "pause_reasons", "maximum_pause_minutes",
		"recipient_strategy", "effective_from", "effective_until", "approved_by", "approved_at",
		"break_glass_reason",
	)

	def validate(self):
		thresholds = (self.warning_minutes, self.breach_minutes, self.escalation_minutes)
		if any(value is None or float(value) <= 0 for value in thresholds):
			frappe.throw("SLA warning, breach, and escalation thresholds must be positive.")
		if self.warning_minutes >= self.breach_minutes:
			frappe.throw("SLA warning must precede breach")
		if self.breach_minutes >= self.escalation_minutes:
			frappe.throw("SLA breach must precede escalation")
		if self.maximum_pause_minutes is None or float(self.maximum_pause_minutes) < 0:
			frappe.throw("Maximum pause minutes cannot be negative.")
		pause_reasons = self.pause_reasons
		if isinstance(pause_reasons, str):
			try:
				pause_reasons = json.loads(pause_reasons)
			except (TypeError, ValueError):
				frappe.throw("Pause reasons must be a JSON list of reason codes.")
		if pause_reasons is not None and (
			not isinstance(pause_reasons, list)
			or any(not isinstance(reason, str) or not reason.strip() for reason in pause_reasons)
			or len(set(pause_reasons)) != len(pause_reasons)
		):
			frappe.throw("Pause reasons must be a unique list of non-empty reason codes.")
		if self.maximum_pause_minutes and not pause_reasons:
			frappe.throw("Pause reasons are required when pauses are enabled.")
		validate_policy_publication(self, self._LOCKED_FIELDS)

	def on_trash(self):
		frappe.throw("Student SLA Policies are retained for audit")
