import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint


class CRMForecastValue(Document):
	_IMMUTABLE_FIELDS = (
		"scenario",
		"planning_scope",
		"metric_key",
		"period_start",
		"period_end",
		"value_kind",
		"prediction",
		"lower_bound",
		"upper_bound",
		"confidence",
		"recorded_at",
		"revision",
		"supersedes",
		"idempotency_fingerprint",
	)

	def before_validate(self):
		if not self.recorded_at:
			self.recorded_at = frappe.utils.now_datetime()
		if not self.revision:
			self.revision = 1
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"
		if not self.idempotency_fingerprint:
			self.idempotency_fingerprint = stable_fingerprint(
				"forecast",
				self.scenario,
				self.planning_scope,
				self.metric_key,
				self.period_start,
				self.period_end,
				self.value_kind,
				self.revision,
			)

	def validate(self):
		if not self.planning_scope:
			frappe.throw(_("Planning Scope is required."), frappe.ValidationError)
		if self.period_start > self.period_end:
			frappe.throw(_("Period Start must not be after Period End."), frappe.ValidationError)
		if self.value_kind not in {"forecast", "simulation"}:
			frappe.throw(_("Forecast values must be marked forecast or simulation."), frappe.ValidationError)
		if (
			self.lower_bound is not None
			and self.upper_bound is not None
			and self.lower_bound > self.upper_bound
		):
			frappe.throw(_("Lower Bound must not exceed Upper Bound."), frappe.ValidationError)
		if not 0 <= float(self.confidence or 0) <= 100:
			frappe.throw(_("Confidence must be between 0 and 100."), frappe.ValidationError)
		if not self.idempotency_fingerprint:
			frappe.throw(_("Idempotency Fingerprint is required."), frappe.ValidationError)
		if int(self.revision or 0) > 1 and not self.supersedes:
			frappe.throw(_("Supersedes is required for a forecast correction."), frappe.ValidationError)
		previous = self.get_doc_before_save()
		if previous and any(
			self.get(fieldname) != previous.get(fieldname) for fieldname in self._IMMUTABLE_FIELDS
		):
			frappe.throw(_("Forecast values are immutable; write a new revision."), frappe.PermissionError)

	def on_trash(self):
		frappe.throw(_("Forecast values are append-only."), frappe.PermissionError)
