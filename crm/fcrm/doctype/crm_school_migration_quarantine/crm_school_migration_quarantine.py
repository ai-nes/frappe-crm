from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint


class CRMSchoolMigrationQuarantine(Document):
	def before_validate(self):
		if not self.quarantine_key and self.source_doctype and self.source_name:
			self.quarantine_key = f"{self.source_doctype}:{self.source_name}"
		if int(self.retry_count or 0) < 0:
			frappe.throw(_("Retry Count cannot be negative."), frappe.ValidationError)
		if not self.payload_hash and self.source_doctype and self.source_name:
			self.payload_hash = stable_fingerprint(self.source_doctype, self.source_name, self.reason)
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"

	def on_trash(self):
		frappe.throw(_("Quarantine evidence is append-only."), frappe.PermissionError)
