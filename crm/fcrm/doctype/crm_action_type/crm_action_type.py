import frappe
from frappe.model.document import Document

from crm.fcrm.action_type_catalog import ACTION_TYPE_CATEGORIES, is_valid_configuration_code


class CRMActionType(Document):
	"""One category shared by built-in or custom CRM Actions."""

	def validate(self):
		if not is_valid_configuration_code(self.action_type):
			frappe.throw(
				"CRM Action Type code must contain only uppercase letters, numbers, and underscores.",
				frappe.ValidationError,
			)
		if not self.display_name or not self.display_name.strip():
			frappe.throw("CRM Action Type display name is required.", frappe.ValidationError)
		if self.sort_order is None:
			frappe.throw("CRM Action Type sort order is required.", frappe.ValidationError)

	def on_trash(self):
		if self.action_type in ACTION_TYPE_CATEGORIES:
			frappe.throw(
				"Built-in CRM Action Types cannot be deleted; disable them instead.",
				frappe.ValidationError,
			)
		for doctype, fieldname in (("CRM Action", "action_type"), ("CRM Action Item", "action_type")):
			if frappe.db.exists("DocType", doctype) and frappe.db.exists(doctype, {fieldname: self.action_type}):
				frappe.throw(
					"CRM Action Type cannot be deleted while CRM records still reference it.",
					frappe.ValidationError,
				)
