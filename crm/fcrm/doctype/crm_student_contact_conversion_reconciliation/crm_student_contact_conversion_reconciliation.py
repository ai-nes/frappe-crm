"""Immutable, redacted evidence for Phase 8 migration/reconciliation runs."""

from __future__ import annotations

import frappe
from frappe.model.document import Document

SERVICE_FLAG = "student_contact_conversion_reconciliation_service"


def _service_write_enabled() -> bool:
	return bool(getattr(frappe.flags, SERVICE_FLAG, False))


class CRMStudentContactConversionReconciliation(Document):
	"""One immutable report per run; it is never a conversion state."""

	def before_validate(self):
		if self.is_new() and not _service_write_enabled():
			frappe.throw(
				"Reconciliation reports may only be written by the migration service.",
				frappe.PermissionError,
			)

	def validate(self):
		if not self.is_new():
			frappe.throw("Reconciliation reports are immutable.", frappe.PermissionError)

	def on_trash(self):
		frappe.throw("Reconciliation reports are append-only and cannot be deleted.", frappe.PermissionError)
