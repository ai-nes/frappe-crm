import frappe
from frappe.model.document import Document

from crm.fcrm.student_operational_state import validate_state_transition


class CRMStudentSLAAttempt(Document):
	"""One first-response clock per opening ownership revision."""

	_IDENTITY_FIELDS = (
		"attempt_key", "reset_sequence", "student", "opening_ownership_revision", "opening_revision_key",
		"opening_ownership_event", "owner_staff", "owning_team", "student_pool", "campus", "sla_policy",
		"sla_policy_version", "warning_at", "breach_at", "escalation_at", "pause_reasons",
		"maximum_pause_minutes", "recipient_strategy", "opened_at", "correlation_token",
	)

	def validate(self):
		validate_state_transition(
			self,
			"student_sla_service",
			{
				"open": {"paused", "warned", "responded", "breached", "closed_inactive", "superseded"},
				"paused": {"open", "responded", "closed_inactive", "superseded"},
				"warned": {"responded", "breached", "closed_inactive", "superseded"},
				"breached": {"escalated", "responded", "closed_inactive", "superseded"},
				"escalated": {"responded", "closed_inactive", "superseded"},
			},
		)
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if previous:
			for fieldname in self._IDENTITY_FIELDS:
				if self.get(fieldname) != previous.get(fieldname):
					frappe.throw(f"{fieldname} is immutable on a Student SLA Attempt")

	def on_trash(self):
		frappe.throw("Student SLA Attempts are retained for audit")
