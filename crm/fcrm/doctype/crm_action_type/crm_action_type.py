import frappe
from frappe.model.document import Document

from crm.fcrm.action_type_catalog import ACTION_TYPE_CATEGORIES


class CRMActionType(Document):
	"""One category shared by many canonical CRM Actions."""

	def validate(self):
		if self.action_type not in ACTION_TYPE_CATEGORIES:
			frappe.throw("CRM Action Type code must be one of the canonical categories.", frappe.ValidationError)
		if not self.action_type or not self.action_type.strip():
			frappe.throw("CRM Action Type code is required.", frappe.ValidationError)
		if not self.display_name or not self.display_name.strip():
			frappe.throw("CRM Action Type display name is required.", frappe.ValidationError)
		if self.sort_order is None:
			frappe.throw("CRM Action Type sort order is required.", frappe.ValidationError)
