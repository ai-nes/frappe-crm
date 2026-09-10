import frappe
from frappe.model.document import Document


class CRMStudentSLADeliveryAttempt(Document):
	"""Provider-submission evidence with a service-fenced completion update."""

	_IDENTITY_FIELDS = ("delivery_attempt_key", "parent", "parenttype", "parentfield", "recipient", "attempt_number", "provider_submission_key")

	def validate(self):
		if not getattr(frappe.flags, "student_sla_delivery_service", False):
			frappe.throw("Student SLA Delivery Attempts can only be created by the delivery service.")
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			frappe.throw("Student SLA Delivery Attempt history is unavailable")
		for fieldname in self._IDENTITY_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"{fieldname} is immutable on a Student SLA Delivery Attempt")
		if previous.outcome == "delivered":
			if self.outcome != "delivered":
				frappe.throw("A delivered provider submission is immutable")
			return
		if previous.outcome not in {"submitted", "unknown"} or self.outcome not in {"submitted", "delivered", "failed", "unknown"}:
			frappe.throw("Invalid provider submission outcome transition")

	def on_trash(self):
		frappe.throw("Student SLA Delivery Attempts are append-only")
