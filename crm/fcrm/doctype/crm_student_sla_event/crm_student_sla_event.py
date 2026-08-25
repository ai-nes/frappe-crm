import frappe
from frappe.model.document import Document

_PAYLOAD_KEYS = {
	"opened": {"owner_staff", "owning_team", "student_pool"},
	"warned": {"due_at"},
	"paused": {"reason_code", "resume_at"},
	"resumed": {"pause_minutes"},
	"pause_expired": {"pause_minutes"},
	"breached": {"due_at"},
	"escalated": {"recipient_role"},
	"responded": {"interaction"},
	"closed": {"reason_code"},
	"reset_approved": {"prior_attempt", "approver", "replacement_attempt"},
	"reset_requested": {"reason_code", "evidence_reference"},
}


class CRMStudentSLAEvent(Document):
	"""Append-only, PII-minimized SLA state-change evidence."""

	_EVENT_TYPES = {"opened", "warned", "paused", "resumed", "pause_expired", "breached", "escalated", "responded", "closed", "reset_requested", "reset_approved"}

	def validate(self):
		if not getattr(frappe.flags, "student_sla_service", False):
			frappe.throw("Student SLA Events can only be created by the SLA service.")
		if self.event_type and self.event_type not in self._EVENT_TYPES:
			frappe.throw("Unsupported Student SLA event type")
		payload = self.payload or {}
		if not isinstance(payload, dict) or not set(payload).issubset(_PAYLOAD_KEYS.get(self.event_type, set())):
			frappe.throw("Student SLA event payload contains unsupported or sensitive fields")
		scope = self.scope_snapshot or {}
		if not isinstance(scope, dict) or not set(scope).issubset(
			{"actor_user", "actor_staff", "campus_scope", "team_scope", "student_scope", "target_owner_or_pool"}
		):
			frappe.throw("Student SLA scope snapshot contains unsupported fields")
		if not self.is_new():
			frappe.throw("Student SLA Events are append-only")

	def on_trash(self):
		frappe.throw("Student SLA Events are append-only")
