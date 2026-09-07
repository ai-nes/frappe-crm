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

	def before_insert(self):
		if not getattr(frappe.flags, "case_key_writer", False):
			frappe.throw(
				"Student Case Keys may only be created by the case-key command.",
				frappe.PermissionError,
			)

	def validate(self):
		if self.is_new():
			self._validate_inverse_link()
			return
		previous = self.get_doc_before_save()
		if previous:
			for fieldname in self._IMMUTABLE_FIELDS:
				if self.get(fieldname) != previous.get(fieldname):
					frappe.throw(f"{fieldname} is immutable on a Student Case Key")
		self._validate_inverse_link()

	def _validate_inverse_link(self):
		student = frappe.db.get_value(
			"CRM Lead",
			self.canonical_student,
			["identity", "admission_year", "case_key"],
			as_dict=True,
		)
		if not student:
			frappe.throw("A Case Key must point to an existing canonical Student.", frappe.ValidationError)
		if student.identity not in (None, "", self.identity) or student.admission_year not in (
			None,
			"",
			self.admission_year,
		):
			frappe.throw(
				"Case Key identity and admission year must match the Student.", frappe.ValidationError
			)
		if student.case_key not in (None, "", self.name):
			frappe.throw("The Student already points to another Case Key.", frappe.DuplicateEntryError)

	def on_trash(self):
		frappe.throw("Student Case Keys are append-only")
