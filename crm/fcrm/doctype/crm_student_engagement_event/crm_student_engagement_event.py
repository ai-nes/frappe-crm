import frappe
from frappe import _
from frappe.model.document import Document


class CRMStudentEngagementEvent(Document):
	def before_insert(self):
		if not getattr(frappe.flags, "student_engagement_projection_writer", False):
			frappe.throw(_("Engagement Events are projection-only; use the source Interaction/Engagement/Outcome."), frappe.PermissionError)

	def before_validate(self):
		if not self.schema_version:
			self.schema_version = "admissions-erd-v2"

	def validate(self):
		if self.is_new():
			return
		before = self.get_doc_before_save()
		if before and any(self.get(fieldname) != before.get(fieldname) for fieldname in self.meta.get_fieldnames()):
			frappe.throw(_("Student engagement events are append-only."), frappe.ValidationError)

	def on_trash(self):
		frappe.throw(_("Student engagement events cannot be deleted."), frappe.PermissionError)
