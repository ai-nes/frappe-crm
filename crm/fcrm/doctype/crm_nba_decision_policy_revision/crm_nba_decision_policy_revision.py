import frappe
from frappe.model.document import Document


class CRMNBADecisionPolicyRevision(Document):
	"""Immutable approved kernel snapshot used for historical replay."""

	def validate(self):
		if self.get_doc_before_save():
			frappe.throw("Approved NBA policy revisions are immutable.", frappe.PermissionError)
		if not self.snapshot or not self.snapshot_digest:
			frappe.throw("A policy revision requires a complete snapshot and digest.", frappe.ValidationError)
		if self.status not in {"approved", "rolled_back", "superseded"}:
			frappe.throw("Invalid policy revision status.", frappe.ValidationError)

	def on_trash(self):
		frappe.throw("Approved NBA policy revisions cannot be deleted.", frappe.PermissionError)
