import frappe
from frappe.model.document import Document

from crm.fcrm.student_operational_state import validate_state_transition


class CRMStudentSLADelivery(Document):
	"""A leased notification projection, mutable only through its fenced service."""

	_IDENTITY_FIELDS = ("delivery_key", "sla_event", "student", "channel", "recipient_role", "idempotency_key", "correlation_token")

	def validate(self):
		validate_state_transition(
			self,
			"student_sla_delivery_service",
			{
				"pending": {"leased", "cancelled"},
				"leased": {"pending", "delivering", "delivered", "failed", "cancelled"},
				"delivering": {"pending", "delivered", "failed", "cancelled"},
				"failed": {"leased", "cancelled"},
			},
		)
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if previous:
			for fieldname in self._IDENTITY_FIELDS:
				if self.get(fieldname) != previous.get(fieldname):
					frappe.throw(f"{fieldname} is immutable on a Student SLA Delivery")

	def on_trash(self):
		frappe.throw("Student SLA Deliveries are retained for audit")
