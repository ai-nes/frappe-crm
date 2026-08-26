import frappe
from frappe.model.document import Document


class CRMStudentCaseKey(Document):
	"""The identity/cycle key is immutable once issued."""

	_IMMUTABLE_FIELDS = (
		"case_key",
		"identity",
		"admission_year",
		"canonical_student",
		"source_student",
		"source_reference_history",
	)

	def validate(self):
		if self.is_new():
			return
		previous = self.get_doc_before_save()
		if not previous:
			return
		for fieldname in self._IMMUTABLE_FIELDS:
			if self.get(fieldname) != previous.get(fieldname):
				frappe.throw(f"{fieldname} is immutable on a Student Case Key")

	def on_trash(self):
		frappe.throw("Student Case Keys are append-only")
