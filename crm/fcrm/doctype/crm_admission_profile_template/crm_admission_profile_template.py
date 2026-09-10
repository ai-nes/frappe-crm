import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.student_profile import (
	TEMPLATE_KINDS,
	TEMPLATE_PROFILE_TYPES,
	TEMPLATE_STATUSES,
	validate_profile_document_type_rows,
)


class CRMAdmissionProfileTemplate(Document):
	_IMMUTABLE_CONTENT_FIELDS = (
		"template_code",
		"template_name",
		"template_kind",
		"profile_type",
		"education_program",
		"admission_method",
		"description",
		"document_types",
	)

	def validate(self):
		self.template_kind = self.template_kind or "standard"
		if not str(self.template_code or "").strip() or not str(self.template_name or "").strip():
			frappe.throw(_("Template code and name are required."), frappe.ValidationError)
		if self.template_kind not in TEMPLATE_KINDS:
			frappe.throw(_("Template kind is invalid."), frappe.ValidationError)
		if self.profile_type not in TEMPLATE_PROFILE_TYPES:
			frappe.throw(_("Profile type is invalid."), frappe.ValidationError)
		if self.status not in TEMPLATE_STATUSES:
			frappe.throw(_("Template status is invalid."), frappe.ValidationError)
		validate_profile_document_type_rows(self)
		self._validate_immutable_used_template()

	def _validate_immutable_used_template(self):
		if self.is_new():
			return
		if getattr(frappe.flags, "admission_profile_template_admin_update", False):
			if self.get_doc_before_save().status == "Archived":
				frappe.throw(
					_("Archived templates are immutable; create a new template instead."),
					frappe.PermissionError,
				)
			return
		before = self.get_doc_before_save()
		if not before or before.status not in {"Active", "Archived"}:
			return
		changed = any(
			self.get(fieldname) != before.get(fieldname) for fieldname in self._IMMUTABLE_CONTENT_FIELDS
		)
		if changed:
			frappe.throw(
				_("Active or archived templates are immutable; create a new version instead."),
				frappe.PermissionError,
			)


def on_doctype_update():
	frappe.db.add_unique("CRM Admission Profile Template", ["template_code"])
