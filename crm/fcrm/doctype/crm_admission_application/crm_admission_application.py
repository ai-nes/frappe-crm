import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_canonical_contracts import canonical_attempt_key
from crm.fcrm.admissions_migration import provenance

APPLICATION_STATUSES = frozenset(
	{"Draft", "Submitted", "Under Review", "Accepted", "Enrolled", "Lost", "Withdrawn"}
)


class CRMAdmissionApplication(Document):
	def before_validate(self):
		if not self.schema_version:
			self.schema_version = "admissions-erd"
		if self.offering and not self.admission_year:
			offering = frappe.db.get_value(
				"CRM Admission Offering",
				self.offering,
				["admission_year", "major", "campus", "admission_method"],
				as_dict=True,
			)
			if offering:
				for fieldname in ("admission_year", "major", "campus", "admission_method"):
					self.set(fieldname, offering.get(fieldname))
		if not self.application_attempt_key and self.case_key and self.offering:
			self.application_attempt_key = canonical_attempt_key(
				self.case_key,
				self.offering,
				self.source_reference or self.source_name or f"student:{self.student}",
			)
		if (
			not self.idempotency_fingerprint
			and self.student
			and self.admission_year
			and self.application_attempt_key
		):
			self.idempotency_fingerprint = provenance(
				source_doctype=self.source_doctype or "CRM Lead",
				source_name=self.source_name or self.student,
				source_reference=self.source_reference,
				admission_year=self.admission_year,
				application_attempt_key=self.application_attempt_key,
			)["idempotency_fingerprint"]

	def validate(self):
		self._validate_case_and_offering()
		if self.status not in APPLICATION_STATUSES:
			frappe.throw(_("Application status is invalid."), frappe.ValidationError)
		if int(self.preference_order or 0) < 1:
			frappe.throw(_("Preference Order must be at least 1."), frappe.ValidationError)
		if int(self.document_total or 0) < 0 or int(self.document_completed or 0) < 0:
			frappe.throw(_("Document counts cannot be negative."), frappe.ValidationError)
		if int(self.document_completed or 0) > int(self.document_total or 0):
			frappe.throw(_("Completed documents cannot exceed total documents."), frappe.ValidationError)
		if not 0 <= float(self.scholarship_percentage or 0) <= 100:
			frappe.throw(_("Scholarship percentage must be between 0 and 100."), frappe.ValidationError)
		if self.status == "Lost" and not str(self.lost_reason or "").strip():
			frappe.throw(_("A lost application requires a reason."), frappe.ValidationError)
		self._validate_immutable_identity()
		if self.status in {"Accepted", "Enrolled"}:
			filters = {
				"case_key": self.case_key,
				"admission_year": self.admission_year,
				"status": ["in", ["Accepted", "Enrolled"]],
			}
			if not self.is_new():
				filters["name"] = ["!=", self.name]
			if frappe.db.exists("CRM Admission Application", filters):
				frappe.throw(
					_("A Case may have only one accepted or enrolled application in an admission year."),
					frappe.DuplicateEntryError,
				)

	def _validate_case_and_offering(self):
		if not self.case_key or not self.offering:
			frappe.throw(_("Case Key and Admission Offering are required."), frappe.ValidationError)
		case = frappe.db.get_value(
			"CRM Student Case Key",
			self.case_key,
			["identity", "admission_year", "canonical_student", "integrity_state"],
			as_dict=True,
		)
		if not case or case.integrity_state != "resolved":
			frappe.throw(
				_("The Student Case Key must be resolved before creating an application."),
				frappe.ValidationError,
			)
		if case.canonical_student != self.student or case.admission_year != self.admission_year:
			frappe.throw(
				_("Application Student and Admission Year must match the Case Key."), frappe.ValidationError
			)
		offering = frappe.db.get_value(
			"CRM Admission Offering",
			self.offering,
			["admission_year", "campus", "major", "admission_method", "status"],
			as_dict=True,
		)
		if not offering or offering.status != "Active":
			frappe.throw(_("Applications may only use an active Admission Offering."), frappe.ValidationError)
		if offering.admission_year != case.admission_year:
			frappe.throw(
				_("Admission Offering and Case Key must use the same admission year."), frappe.ValidationError
			)
		for fieldname in ("major", "campus", "admission_method"):
			if self.get(fieldname) not in (None, "", offering.get(fieldname)):
				frappe.throw(
					_("Application {0} must match the Admission Offering.").format(fieldname),
					frappe.ValidationError,
				)
			self.set(fieldname, offering.get(fieldname))

	def _validate_immutable_identity(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in ("application_attempt_key", "case_key", "student", "offering", "admission_year"):
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(
					_("{0} is immutable on an Admission Application.").format(fieldname),
					frappe.PermissionError,
				)
