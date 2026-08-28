import frappe
from frappe.model.document import Document


class CRMStudentIdentity(Document):
	"""Identity roots are never deleted or edited through generic CRUD."""

	def on_trash(self):
		frappe.throw("Student identities are append-only")
