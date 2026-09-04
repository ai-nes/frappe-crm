import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime

from crm.fcrm.nba_canonical import canonical_digest, timing_policy_snapshot
from crm.fcrm.nba_timing import TIME_SLOTS, slot_bounds


class CRMTimingPolicy(Document):
	"""Reusable timing rules for action scheduling; distinct from Student SLA."""

	def validate(self):
		if self.time_slot and self.time_slot not in TIME_SLOTS:
			frappe.throw("Time slot must be one of: 0-6, 6-12, 12-18, 18-24.", frappe.ValidationError)
		if bool(self.allowed_start_time) != bool(self.allowed_end_time):
			frappe.throw("Allowed start and end times must be provided together.", frappe.ValidationError)
		if self.time_slot and self.allowed_start_time and self.allowed_end_time:
			start, end = slot_bounds(self.time_slot)
			start_matches = str(self.allowed_start_time)[:8] == str(start)[:8]
			end_text = str(self.allowed_end_time)[:8]
			end_matches = end_text == str(end)[:8]
			if not start_matches or not end_matches:
				frappe.throw(
					"Time slot must match the configured allowed start/end time.", frappe.ValidationError
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
		if (
			self.effective_from
			and self.effective_to
			and get_datetime(self.effective_to) <= get_datetime(self.effective_from)
		):
			frappe.throw("effective_to must be after effective_from.", frappe.ValidationError)

	def sync_policy_revision(self) -> bool:
		"""Recompute the timing snapshot; on a change, bump the revision + digest.

		Returns whether a bump occurred. Not called on save yet -- the
		control-plane patch owns the first population.
		"""
		digest = canonical_digest(timing_policy_snapshot(self.as_dict()))
		if digest == (self.policy_digest or ""):
			return False
		self.policy_digest = digest
		self.policy_revision = int(self.policy_revision or 0) + 1
		return True
