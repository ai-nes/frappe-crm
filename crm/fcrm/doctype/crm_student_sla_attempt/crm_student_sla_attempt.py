import frappe
from frappe.model.document import Document

from crm.fcrm.student_operational_state import validate_state_transition


class CRMStudentSLAAttempt(Document):
	"""One first-response clock per opening ownership revision."""

	_IDENTITY_FIELDS = (
		"attempt_key",
		"reset_sequence",
		"student",
		"opening_ownership_revision",
		"opening_revision_key",
		"opening_ownership_event",
		"owner_staff",
		"owning_team",
		"student_pool",
		"campus",
		"sla_policy",
		"sla_policy_version",
		"warning_at",
		"breach_at",
		"escalation_at",
		"pause_reasons",
		"maximum_pause_minutes",
		"recipient_strategy",
		"opened_at",
		"correlation_token",
	)

	@staticmethod
	def default_list_data():
		"""Provide the first-visit columns required by the shared list API."""
		columns = [
			{
				"label": "Student",
				"type": "Link",
				"key": "student",
				"options": "CRM Student",
				"width": "16rem",
			},
			{
				"label": "Owner",
				"type": "Link",
				"key": "owner_staff",
				"options": "CRM Staff",
				"width": "12rem",
			},
			{"label": "Status", "type": "Select", "key": "status", "width": "10rem"},
			{"label": "Warning At", "type": "Datetime", "key": "warning_at", "width": "11rem"},
			{"label": "Breach At", "type": "Datetime", "key": "breach_at", "width": "11rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "student", "owner_staff", "status", "warning_at", "breach_at", "modified"]
		return {"columns": columns, "rows": rows}

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
