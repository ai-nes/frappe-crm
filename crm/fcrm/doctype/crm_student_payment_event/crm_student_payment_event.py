from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint


class CRMStudentPaymentEvent(Document):
	def before_validate(self):
		if not self.event_key and self.payment and self.event_type and self.event_at:
			self.event_key = (
				"PEV-"
				+ stable_fingerprint(
					self.payment,
					self.event_type,
					self.event_at,
					self.amount_delta,
					self.source_reference,
					self.supersedes,
				)[:32]
			)
		if not self.recorded_at:
			self.recorded_at = frappe.utils.now_datetime()
		if not self.schema_version:
			self.schema_version = "admissions-erd"

	def validate(self):
		if self.event_type not in {"Pending", "Received", "Failed", "Refunded", "Corrected"}:
			frappe.throw(_("Payment event type is invalid."), frappe.ValidationError)
		if not self.idempotency_fingerprint:
			frappe.throw(_("Idempotency Fingerprint is required."), frappe.ValidationError)
		payment = frappe.db.get_value("CRM Student Payment", self.payment, ["currency"], as_dict=True)
		if payment and payment.currency != self.currency:
			frappe.throw(_("Payment event currency must match the source Payment."), frappe.ValidationError)
		if self.event_type == "Corrected" and not self.supersedes:
			frappe.throw(
				_("A corrected payment event must supersede an earlier event."), frappe.ValidationError
			)
		if self.supersedes:
			previous = frappe.db.get_value(
				"CRM Student Payment Event", self.supersedes, ["payment"], as_dict=True
			)
			if not previous or previous.payment != self.payment:
				frappe.throw(
					_("A payment event correction must supersede an event for the same Payment."),
					frappe.ValidationError,
				)
		if not self.is_new():
			frappe.throw(_("Payment events are immutable; record a new event."), frappe.PermissionError)

	def before_insert(self):
		if not getattr(frappe.flags, "payment_event_writer", False):
			frappe.throw(
				_("Payment events may only be created by the payment event writer."),
				frappe.PermissionError,
			)

	def on_trash(self):
		frappe.throw(_("Payment events are append-only."), frappe.PermissionError)
