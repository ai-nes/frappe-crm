import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

from crm.fcrm.student_profile import (
	DOCUMENT_STATUSES,
	can_verify_student_document,
	refresh_document_completeness,
	validate_student_document_ownership,
)


class CRMStudentDocument(Document):
	def before_validate(self):
		self.status = self.status or "Uploaded"
		self.is_private = 1
		if self.status == "Verified" and not self.verified_at:
			self.verified_at = now_datetime()
		if self.status == "Verified" and not self.verified_by:
			self.verified_by = frappe.session.user

	def validate(self):
		if int(self.version or 0) < 1:
			frappe.throw(_("Document version must be at least 1."), frappe.ValidationError)
		if self.status not in DOCUMENT_STATUSES:
			frappe.throw(_("Student Document status is invalid."), frappe.ValidationError)
		validate_student_document_ownership(self)
		if self.status == "Rejected" and not str(self.rejection_reason or "").strip():
			frappe.throw(_("A rejected Student Document requires a reason."), frappe.ValidationError)
		if self.status == "Verified":
			if not can_verify_student_document():
				frappe.throw(
					_("Only an authorized admissions reviewer can verify documents."), frappe.PermissionError
				)
			if not self.verified_by or not self.verified_at:
				frappe.throw(
					_("A verified Student Document requires actor and timestamp."), frappe.ValidationError
				)
		self._validate_version_immutability()

	def _validate_version_immutability(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if not before:
			return
		if before.status == "Verified":
			frappe.throw(
				_("Verified Student Documents are immutable; upload a new version."), frappe.PermissionError
			)
		if before.version != self.version and int(self.version or 0) < int(before.version or 0):
			frappe.throw(_("Student Document version cannot decrease."), frappe.ValidationError)

	def on_update(self):
		refresh_document_completeness(self.student_admission_profile)

	def on_trash(self):
		frappe.throw(_("Student Documents are retained as submission history."), frappe.PermissionError)


def get_permission_query_conditions(user=None):
	from crm.fcrm.permissions import get_permission_query_conditions

	condition = get_permission_query_conditions("CRM Student", user=user)
	if condition is None:
		return None
	if condition == "1=0":
		return condition
	return (
		"`tabCRM Student Document`.student in (select `tabCRM Student`.name from `tabCRM Student` "
		f"where ({condition}))"
	)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	student = doc.get("student") if hasattr(doc, "get") else getattr(doc, "student", None)
	if not student:
		return False
	return frappe.has_permission("CRM Student", permission_type or ptype or "read", student, user=user)
