import frappe
from frappe.model.document import Document

from crm.fcrm.nba_timing import TIME_SLOTS, slot_bounds


class CRMTimingPolicy(Document):
	"""Reusable timing rules for action scheduling; distinct from Student SLA."""

	def validate(self):
		if self.time_slot and self.time_slot not in TIME_SLOTS:
			frappe.throw("Time slot must be one of: 0-6, 6-12, 12-18, 18-24.", frappe.ValidationError)
		if bool(self.allowed_start_time) != bool(self.allowed_end_time):
			frappe.throw(
				"Allowed start and end times must be provided together.", frappe.ValidationError
			)
		if self.time_slot and self.allowed_start_time and self.allowed_end_time:
			start, end = slot_bounds(self.time_slot)
			start_matches = str(self.allowed_start_time)[:8] == str(start)[:8]
			end_text = str(self.allowed_end_time)[:8]
			end_matches = end_text == str(end)[:8]
			if not start_matches or not end_matches:
				frappe.throw("Time slot must match the configured allowed start/end time.", frappe.ValidationError)
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
