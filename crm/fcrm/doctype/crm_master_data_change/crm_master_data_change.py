import frappe
from frappe.model.document import Document


class CRMMasterDataChange(Document):
	def before_insert(self):
		if not frappe.flags.get("crm_governance_log_insert"):
			frappe.throw("Master-data changes may only be created through the governance command.", frappe.PermissionError)

	def validate(self):
		from crm.fcrm.master_data_governance import GOVERNED_DOCTYPES
		from crm.fcrm.governed_reference_registry import REGISTRY_REVISION
		if self.reference_doctype not in GOVERNED_DOCTYPES:
			frappe.throw(f"{self.reference_doctype} is not a governed master data type")
		if self.change_kind == "break_glass" and not self.nonce_hash:
			frappe.throw("Break-glass changes require nonce evidence.", frappe.ValidationError)
		if self.registry_revision and self.registry_revision != REGISTRY_REVISION:
			frappe.throw("Unknown governance registry revision")

	def on_update(self):
		if not (frappe.flags.get("crm_governance_log_update") or frappe.flags.get("crm_governance_log_insert")):
			frappe.throw("Master-data changes are append-only evidence.", frappe.PermissionError)

	def on_trash(self):
		if getattr(frappe.flags, "in_test", False):
			return
		frappe.throw("Master-data changes are append-only evidence.", frappe.PermissionError)
