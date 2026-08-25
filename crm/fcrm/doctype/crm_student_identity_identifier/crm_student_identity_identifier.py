import frappe
from frappe.model.document import Document


class CRMStudentIdentityIdentifier(Document):
	"""Identifier observations are service-created audit evidence."""

	def on_trash(self):
		frappe.throw("Student identity identifiers are append-only")
