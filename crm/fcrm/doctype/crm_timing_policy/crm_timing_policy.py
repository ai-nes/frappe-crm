import frappe
from frappe.model.document import Document


class CRMTimingPolicy(Document):
	"""Reusable timing rules for action scheduling; distinct from Student SLA."""

	def validate(self):
		if bool(self.allowed_start_time) != bool(self.allowed_end_time):
			frappe.throw(
				"Allowed start and end times must be provided together.", frappe.ValidationError
			)
		if self.delay_value is not None and float(self.delay_value) < 0:
			frappe.throw("Delay value cannot be negative.", frappe.ValidationError)
		if self.deadline_offset is not None and float(self.deadline_offset) < 0:
			frappe.throw("Deadline offset cannot be negative.", frappe.ValidationError)
		if int(self.recurrence_interval or 1) < 1:
			frappe.throw("Recurrence interval must be at least one.", frappe.ValidationError)
		if self.deadline_type == "business_days" and float(self.deadline_offset or 0) % 1:
			frappe.throw("Business-day deadline offset must be a whole number.", frappe.ValidationError)
		if self.trigger_type == "event" and not self.trigger_event:
			frappe.throw("Event timing policies require trigger_event.", frappe.ValidationError)
		if self.optimization_enabled and not self.optimization_objective:
			frappe.throw(
				"Optimization objective is required when optimization is enabled.", frappe.ValidationError
			)
