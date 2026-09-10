import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_migration import stable_fingerprint
from crm.fcrm.student_reference import canonical_student


class CRMStudentPayment(Document):
	_IMMUTABLE_FIELDS = (
		"transaction_key",
		"application",
		"student",
		"payment_reference",
		"amount",
		"currency",
		"status",
		"received_at",
		"payment_method",
		"business_period",
		"timezone",
		"source_system",
		"source_run",
		"recorded_at",
		"revision",
		"idempotency_fingerprint",
	)

	def before_validate(self):
		self.student = canonical_student(self.student) or self.student
		if not self.transaction_key and self.payment_reference:
			self.transaction_key = self.payment_reference
		if not self.business_period:
			self.business_period = frappe.utils.today()
		if not self.recorded_at:
			self.recorded_at = frappe.utils.now_datetime()
		if not self.source_system:
			self.source_system = "crm"
		if not self.source_run:
			self.source_run = f"payment:{self.transaction_key}"
		if not self.revision:
			self.revision = 1
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"
		if not self.idempotency_fingerprint:
			self.idempotency_fingerprint = stable_fingerprint(
				"payment",
				self.transaction_key,
				self.application,
				self.student,
				self.amount,
				self.currency,
				self.business_period,
				self.revision,
				self.source_system,
				self.source_run,
			)

	def validate(self):
		if self.payment_type not in {
			"booking_fee",
			"enrollment_fee",
			"supplemental_enrollment_fee",
			"tuition_fee",
			"refund",
			"other",
		}:
			frappe.throw(_("Payment type is invalid."), frappe.ValidationError)
		if float(self.amount or 0) < 0:
			frappe.throw(_("Payment amount cannot be negative."), frappe.ValidationError)
		if not self.idempotency_fingerprint:
			frappe.throw(_("Idempotency Fingerprint is required."), frappe.ValidationError)
		application = frappe.db.get_value(
			"CRM Admission Application", self.application, ["student"], as_dict=True
		)
		if application:
			if application.student != self.student:
				frappe.throw(
					_("Payment Student must match the Admission Application."), frappe.ValidationError
				)
		if not self.is_new():
			previous = self.get_doc_before_save()
			if previous and any(
				self.get(fieldname) != previous.get(fieldname) for fieldname in self._IMMUTABLE_FIELDS
			):
				frappe.throw(
					_("Payments are immutable; record a Payment Event for status or refund changes."),
					frappe.PermissionError,
				)

	def on_trash(self):
		frappe.throw(_("Payments are append-only."), frappe.PermissionError)
