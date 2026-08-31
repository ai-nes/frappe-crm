from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_canonical_contracts import validate_metric_definition


class CRMMetricDefinition(Document):
	def validate(self):
		validate_metric_definition(self.as_dict())
		if int(self.version or 0) < 1:
			frappe.throw(_("Definition Version must be positive."), frappe.ValidationError)
		if self.effective_until and self.effective_from > self.effective_until:
			frappe.throw(_("Effective Until must not be before Effective From."), frappe.ValidationError)
		if not isinstance(self.stage_mapping, (dict, list)):
			frappe.throw(_("Stage Mapping must be JSON."), frappe.ValidationError)
