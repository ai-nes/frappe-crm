import frappe
from frappe.model.document import Document


class CRMEnrollmentTransition(Document):
	"""Append-only log of `CRM Student.enrollment_status` changes.

	Rows are written exclusively through
	`crm.fcrm.doctype.crm_student.enrollment_transition.record_transition` —
	never insert/edit rows here directly, the from_date/to_date/duration
	bookkeeping (closing the previous open row) lives in that module.
	"""

	def before_insert(self):
		if not self.from_date:
			self.from_date = frappe.utils.now_datetime()
