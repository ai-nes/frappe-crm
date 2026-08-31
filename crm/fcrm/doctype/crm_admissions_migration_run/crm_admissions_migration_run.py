from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import CANONICAL_MIGRATION_ORDER


class CRMAdmissionsMigrationRun(Document):
	def before_validate(self):
		if not self.schema_version:
			self.schema_version = "admissions-migration-v1"
		if int(self.batch_size or 0) < 1:
			frappe.throw(_("Batch Size must be positive."), frappe.ValidationError)

	def validate(self):
		if self.phase not in CANONICAL_MIGRATION_ORDER:
			frappe.throw(_("Migration phase is not in the canonical order."), frappe.ValidationError)
		if self.status == "Completed" and not self.completed_at:
			frappe.throw(
				_("A completed migration run requires a completion timestamp."), frappe.ValidationError
			)
