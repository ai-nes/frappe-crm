import frappe
from frappe.model.document import Document


class CRMMasterDataChangeLog(Document):
	def before_insert(self):
		if not frappe.flags.get("crm_governance_log_insert"):
			frappe.throw("Change logs may only be created through the governance command.", frappe.PermissionError)

	def validate(self):
		from crm.fcrm.master_data_governance import GOVERNED_DOCTYPES

		if self.reference_doctype not in GOVERNED_DOCTYPES:
			frappe.throw(f"{self.reference_doctype} is not a governed master data type")
		if self.registry_revision and self.registry_revision != "P9-DEC-001":
			frappe.throw("Unknown governance registry revision")

	def on_update(self):
		if not (
			frappe.flags.get("crm_governance_log_update")
			or frappe.flags.get("crm_governance_log_insert")
		):
			frappe.throw("Change logs are append-only evidence.", frappe.PermissionError)

	def on_trash(self):
		if frappe.flags.in_test:
			return
		frappe.throw("Change logs are append-only evidence.", frappe.PermissionError)
