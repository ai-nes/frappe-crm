import frappe
from frappe import _
from frappe.model.document import Document

LINE_KINDS = {"tuition", "scholarship", "quota"}


class CRMAcademicYearConfig(Document):
	def validate(self):
		if not self.admission_year:
			frappe.throw(_("Admission Year is required."), frappe.ValidationError)
		if frappe.db.exists(
			"CRM Academic Year Config",
			{"admission_year": self.admission_year, "name": ["!=", self.name]},
		):
			frappe.throw(
				_("Only one Academic Year Config is allowed for each Admission Year."),
				frappe.DuplicateEntryError,
			)

		seen = set()
		for line in self.lines or []:
			if line.line_kind not in LINE_KINDS:
				frappe.throw(_("Invalid academic year line kind."), frappe.ValidationError)
			key = (line.line_kind, line.campus, line.major)
			if key in seen:
				frappe.throw(
					_("Duplicate academic year line for {0}, {1}, {2}.").format(*key),
					frappe.DuplicateEntryError,
				)
			seen.add(key)
