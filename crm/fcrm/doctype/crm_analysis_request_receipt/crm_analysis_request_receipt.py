import frappe
from frappe.model.document import Document

from crm.fcrm.analysis_runs import MAX_IDEMPOTENCY_KEY_LENGTH


class CRMAnalysisRequestReceipt(Document):
	def validate(self):
		if not self.requester or not self.idempotency_key or len(self.idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
			frappe.throw("Analysis request receipt identity is invalid.", frappe.ValidationError)
		if not self.request_fingerprint or len(self.request_fingerprint) != 64:
			frappe.throw("Analysis request receipt fingerprint is invalid.", frappe.ValidationError)
