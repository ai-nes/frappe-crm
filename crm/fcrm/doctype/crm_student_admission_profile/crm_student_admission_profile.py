import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.student_profile import (
	ENROLLMENT_STATUSES,
	PROFILE_STATUSES,
	refresh_document_completeness,
	validate_profile_completeness,
)


class CRMStudentAdmissionProfile(Document):
	def before_validate(self):
		self.profile_status = self.profile_status or "Draft"
		self.enrollment_status = self.enrollment_status or "Not Started"
		if self.application and self.student and self.admission_year:
			self.attempt_key = f"application:{self.application}"
		elif not self.attempt_key and self.student and self.admission_year and self.profile_template:
			self.attempt_key = (
				f"{self.student}|{self.admission_year}|{self.profile_template}|{self.attempt_number or 1}"
			)

	def validate(self):
		if int(self.attempt_number or 0) < 1:
			frappe.throw(_("Attempt Number must be at least 1."), frappe.ValidationError)
		if self.profile_status not in PROFILE_STATUSES:
			frappe.throw(_("Student admission profile status is invalid."), frappe.ValidationError)
		if self.enrollment_status not in ENROLLMENT_STATUSES:
			frappe.throw(_("Enrollment status is invalid."), frappe.ValidationError)
		if not self.student or not frappe.db.exists("CRM Student", self.student):
			frappe.throw(_("A valid Student is required."), frappe.ValidationError)
		template = frappe.db.get_value(
			"CRM Admission Profile Template", self.profile_template, ["status"], as_dict=True
		)
		if not template:
			frappe.throw(_("A valid admission profile template is required."), frappe.ValidationError)
		if self.profile_status == "Active":
			if template.status != "Active":
				frappe.throw(
					_("Only an active template can activate a Student profile."), frappe.ValidationError
				)
			validate_profile_completeness(self, strict=True)
		self._validate_application_student()
		self._validate_unique_application_profile()
		self._validate_unique_active_profile()
		self._validate_lifecycle_transition()

	def _validate_application_student(self):
		if not self.application:
			return
		application_student = frappe.db.get_value("CRM Admission Application", self.application, "student")
		if application_student and application_student != self.student:
			frappe.throw(
				_("Application and Student admission profile must use the same Student."),
				frappe.ValidationError,
			)

	def _validate_unique_application_profile(self):
		if not self.application:
			return
		filters = {"application": self.application}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("CRM Student Admission Profile", filters):
			frappe.throw(
				_("An Admission Application can have only one Student admission profile."),
				frappe.DuplicateEntryError,
			)

	def _validate_unique_active_profile(self):
		if self.profile_status != "Active":
			return
		if self.application:
			return
		filters = {
			"student": self.student,
			"admission_year": self.admission_year,
			"profile_template": self.profile_template,
			"attempt_key": self.attempt_key,
			"profile_status": "Active",
		}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("CRM Student Admission Profile", filters):
			frappe.throw(
				_("An active Student profile already exists for this admission attempt."),
				frappe.DuplicateEntryError,
			)

	def _validate_lifecycle_transition(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if before.profile_status == "Archived" and self.profile_status != "Archived":
			frappe.throw(_("Archived Student profiles cannot be reopened."), frappe.PermissionError)
		if before.profile_status == "Completed" and self.profile_status not in {"Completed", "Archived"}:
			frappe.throw(_("Completed Student profiles cannot move backwards."), frappe.PermissionError)

	def on_update(self):
		refresh_document_completeness(self.name)
