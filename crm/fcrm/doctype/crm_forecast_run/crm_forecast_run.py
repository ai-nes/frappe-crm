import frappe
from frappe import _
from frappe.model.document import Document


class CRMForecastRun(Document):
	_IMMUTABLE_FIELDS = (
		"model_version",
		"as_of",
		"horizon_start",
		"horizon_end",
		"planning_scope",
		"source_snapshot",
		"recorded_at",
	)

	def before_validate(self):
		if not self.recorded_at:
			self.recorded_at = frappe.utils.now_datetime()
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"

	def validate(self):
		if not self.planning_scope:
			frappe.throw(_("Planning Scope is required."), frappe.ValidationError)
		if self.horizon_start > self.horizon_end:
			frappe.throw(_("Horizon Start must not be after Horizon End."), frappe.ValidationError)
		previous = self.get_doc_before_save()
		if previous and previous.status == "Completed":
			if (
				any(self.get(fieldname) != previous.get(fieldname) for fieldname in self._IMMUTABLE_FIELDS)
				or self.status != "Completed"
			):
				frappe.throw(_("A completed Forecast Run is immutable."), frappe.PermissionError)
