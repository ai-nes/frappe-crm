import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint


class CRMTarget(Document):
	def before_validate(self):
		if not self.idempotency_fingerprint:
			self.idempotency_fingerprint = stable_fingerprint(
				"target",
				self.admission_year,
				self.period_start,
				self.period_end,
				self.metric_key,
				self.planning_scope,
				self.version,
			)

	def validate(self):
		if not self.planning_scope:
			frappe.throw(_("Planning Scope is required."), frappe.ValidationError)
		if self.period_start > self.period_end:
			frappe.throw(_("Period Start must not be after Period End."))
		if self.effective_until and self.effective_from > self.effective_until:
			frappe.throw(_("Effective From must not be after Effective Until."))
		if float(self.target_value or 0) < 0:
			frappe.throw(_("Target Value cannot be negative."))
		if self.status == "Approved" and not self.effective_from:
			frappe.throw(_("An approved target requires an effective date."))

	@classmethod
	def approved_filters(cls, *, admission_year, period_start, period_end, metric_key, planning_scope):
		return {
			"admission_year": admission_year,
			"period_start": ["<=", period_end],
			"period_end": [">=", period_start],
			"metric_key": metric_key,
			"planning_scope": planning_scope,
			"status": "Approved",
		}
