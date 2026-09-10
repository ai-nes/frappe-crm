import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint


class CRMRevenueRecognition(Document):
	_IMMUTABLE_FIELDS = (
		"ledger_entry_key",
		"payment",
		"application",
		"student",
		"gross_amount",
		"award_amount",
		"recognized_amount",
		"currency",
		"status",
		"recognized_at",
		"recognition_period",
		"timezone",
		"source_system",
		"source_run",
		"recorded_at",
		"revision",
		"supersedes",
		"idempotency_fingerprint",
		"verification_status",
	)

	def before_validate(self):
		if not self.ledger_entry_key and self.payment and self.recognition_period:
			self.ledger_entry_key = f"{self.payment}|{self.recognition_period}|{self.revision or 1}"
		if not self.recorded_at:
			self.recorded_at = frappe.utils.now_datetime()
		if not self.source_system:
			self.source_system = "crm"
		if not self.source_run:
			self.source_run = f"revenue:{self.payment}:{self.recognition_period}"
		if not self.revision:
			self.revision = 1
		if not self.schema_version:
			self.schema_version = "admissions-erd"
		if not self.idempotency_fingerprint:
			self.idempotency_fingerprint = stable_fingerprint(
				"revenue",
				self.payment,
				self.application,
				self.student,
				self.recognition_period,
				self.recognized_amount,
				self.currency,
				self.revision,
				self.source_system,
				self.source_run,
			)

	def validate(self):
		if (
			float(self.gross_amount or 0) < 0
			or float(self.award_amount or 0) < 0
			or float(self.recognized_amount or 0) < 0
		):
			frappe.throw(_("Revenue amounts cannot be negative."), frappe.ValidationError)
		if float(self.recognized_amount or 0) > float(self.gross_amount or 0) - float(self.award_amount or 0):
			frappe.throw(
				_("Recognized amount cannot exceed gross amount less award amount."), frappe.ValidationError
			)
		if not self.idempotency_fingerprint:
			frappe.throw(_("Idempotency Fingerprint is required."), frappe.ValidationError)
		payment = frappe.db.get_value(
			"CRM Student Payment", self.payment, ["application", "student", "currency"], as_dict=True
		)
		if payment and (
			payment.application != self.application
			or payment.student != self.student
			or payment.currency != self.currency
		):
			frappe.throw(_("Revenue lineage must match the source Payment."), frappe.ValidationError)
		if int(self.revision or 0) > 1 and not self.supersedes:
			frappe.throw(
				_("A revenue correction must supersede an earlier ledger entry."), frappe.ValidationError
			)
		if not self.is_new():
			previous = self.get_doc_before_save()
			if previous and any(
				self.get(fieldname) != previous.get(fieldname) for fieldname in self._IMMUTABLE_FIELDS
			):
				frappe.throw(
					_("Revenue ledger entries are immutable; record a reversal or correction."),
					frappe.PermissionError,
				)

	def on_trash(self):
		frappe.throw(_("Revenue ledger entries are append-only."), frappe.PermissionError)
