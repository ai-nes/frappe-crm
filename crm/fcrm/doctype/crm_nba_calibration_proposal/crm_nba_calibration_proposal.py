import frappe
from frappe.model.document import Document


class CRMNBACalibrationProposal(Document):
	"""Immutable deterministic calibration report awaiting Director review."""

	def validate(self):
		if self.get_doc_before_save():
			frappe.throw("Calibration proposals are immutable.", frappe.PermissionError)
		if self.status not in {"shadow", "approved", "rejected", "superseded"}:
			frappe.throw("Invalid calibration proposal status.", frappe.ValidationError)
		if self.status == "approved" and not self.approved_by:
			frappe.throw("Approved calibration proposals require an approver.", frappe.ValidationError)

	def on_trash(self):
		frappe.throw("Calibration proposals cannot be deleted.", frappe.PermissionError)
