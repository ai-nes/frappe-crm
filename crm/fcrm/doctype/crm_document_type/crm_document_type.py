import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.student_profile import DOCUMENT_CATEGORIES


class CRMDocumentType(Document):
	def validate(self):
		if not str(self.code or "").strip() or not str(self.label or "").strip():
			frappe.throw(_("Document Type code and label are required."), frappe.ValidationError)
		if self.category not in DOCUMENT_CATEGORIES:
			frappe.throw(_("Document Type category is invalid."), frappe.ValidationError)
		if self.status not in {"Active", "Archived"}:
			frappe.throw(_("Document Type status is invalid."), frappe.ValidationError)
		if not self.is_active and self.status == "Active":
			frappe.throw(_("An active Document Type must have is_active enabled."), frappe.ValidationError)
		if not self.is_new():
			before = self.get_doc_before_save()
			if before and before.code != self.code:
				frappe.throw(_("Document Type code is immutable."), frappe.PermissionError)


def on_doctype_update():
	frappe.db.add_unique("CRM Document Type", ["code"])
