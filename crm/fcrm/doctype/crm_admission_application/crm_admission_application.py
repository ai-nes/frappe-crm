import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.admissions_canonical_contracts import canonical_application_attempt_key
from crm.fcrm.admissions_migration import provenance
from crm.fcrm.student_reference import canonical_student

APPLICATION_STATUSES = frozenset(
	{"Draft", "Submitted", "Under Review", "Accepted", "Enrolled", "Lost", "Withdrawn"}
)


class CRMAdmissionApplication(Document):
	def after_insert(self):
		# Keep standard Frappe document creation consistent with the command API.
		# Patch/backfill jobs can create historical applications before templates
		# are configured; the command/API will materialize them on replay.
		if getattr(frappe.flags, "in_patch", False) or getattr(
			frappe.flags, "admission_application_service", False
		):
			return
		from crm.fcrm.admission_application import materialize_admission_profile

		materialize_admission_profile(self)

	def before_validate(self):
		self._normalize_canonical_student()
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"
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
		if self.profile_template:
			self.profile_template = (
				frappe.db.get_value(
					"CRM Admission Profile Template",
					{"template_code": self.profile_template},
					"name",
				)
				or self.profile_template
			)
		if not self.application_attempt_key and self.student and self.offering:
			self.application_attempt_key = canonical_application_attempt_key(
				self.student,
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
				source_doctype=self.source_doctype or "CRM Student",
				source_name=self.source_name or self.student,
				source_reference=self.source_reference,
				admission_year=self.admission_year,
				application_attempt_key=self.application_attempt_key,
			)["idempotency_fingerprint"]

	def validate(self):
		self._validate_student_and_offering()
		self._validate_profile_template()
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
		if not 0 <= float(self.discount_percentage or 0) <= 100:
			frappe.throw(_("Discount percentage must be between 0 and 100."), frappe.ValidationError)
		if float(self.discount_amount or 0) < 0 or float(self.agreed_tuition_fee or 0) < 0:
			frappe.throw(_("Tuition and discount amounts cannot be negative."), frappe.ValidationError)
		if self.status == "Lost" and not str(self.lost_reason or "").strip():
			frappe.throw(_("A lost application requires a reason."), frappe.ValidationError)
		self._validate_immutable_identity()
		if self.status in {"Accepted", "Enrolled"}:
			filters = {
				"student": self.student,
				"admission_year": self.admission_year,
				"status": ["in", ["Accepted", "Enrolled"]],
			}
			if not self.is_new():
				filters["name"] = ["!=", self.name]
			if frappe.db.exists("CRM Admission Application", filters):
				frappe.throw(
					_("A Student may have only one accepted or enrolled application in an admission year."),
					frappe.DuplicateEntryError,
				)

	def _normalize_canonical_student(self):
		raw_reference = self.student or self.crm_student
		student = canonical_student(raw_reference)
		if not student:
			return
		if raw_reference and raw_reference != student and not self.source_lead:
			self.source_lead = raw_reference
		self.student = student
		self.crm_student = student

	def _validate_student_and_offering(self):
		if not self.student or not self.offering:
			frappe.throw(_("Student and Admission Offering are required."), frappe.ValidationError)
		student = frappe.db.get_value("CRM Student", self.student, ["admission_year"], as_dict=True)
		if not student:
			frappe.throw(_("The canonical Student does not exist."), frappe.ValidationError)
		offering = frappe.db.get_value(
			"CRM Admission Offering",
			self.offering,
			["admission_year", "campus", "major", "admission_method", "status"],
			as_dict=True,
		)
		if not offering or offering.status != "Active":
			frappe.throw(_("Applications may only use an active Admission Offering."), frappe.ValidationError)
		if offering.admission_year != self.admission_year:
			frappe.throw(
				_("Admission Offering and Application must use the same admission year."),
				frappe.ValidationError,
			)
		if student.admission_year and student.admission_year != offering.admission_year:
			frappe.throw(
				_("Student and Admission Offering must use the same admission year."), frappe.ValidationError
			)
		for fieldname in ("major", "campus", "admission_method"):
			if self.get(fieldname) not in (None, "", offering.get(fieldname)):
				frappe.throw(
					_("Application {0} must match the Admission Offering.").format(fieldname),
					frappe.ValidationError,
				)
			self.set(fieldname, offering.get(fieldname))

	def _validate_profile_template(self):
		if not self.profile_template:
			return
		template = frappe.db.get_value(
			"CRM Admission Profile Template",
			self.profile_template,
			["status", "profile_type"],
			as_dict=True,
		)
		if not template or template.status != "Active" or template.profile_type != "academic_admission":
			frappe.throw(
				_("Application must use an active academic admission profile template."),
				frappe.ValidationError,
			)

	def _validate_immutable_identity(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in (
			"application_attempt_key",
			"student",
			"offering",
			"admission_year",
			"profile_template",
		):
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(
					_("{0} is immutable on an Admission Application.").format(fieldname),
					frappe.PermissionError,
				)
