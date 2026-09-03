import frappe
from frappe.model.document import Document

from crm.fcrm.action_constraints import validate_action_config
from crm.fcrm.action_type_catalog import ACTION_TYPE_CODES, ACTION_TYPE_METADATA


class CRMAction(Document):
	"""Master catalog row for one of the 79 selectable CRM Actions."""

	def validate(self):
		if self.code not in ACTION_TYPE_CODES:
			frappe.throw("CRM Action code must be one of the canonical 79 codes.", frappe.ValidationError)
		expected_category = ACTION_TYPE_METADATA[self.code]["category"]
		if self.action_type != expected_category:
			frappe.throw(
				f"CRM Action {self.code} must use Action Type {expected_category}.",
				frappe.ValidationError,
			)
		if not self.display_name or not self.display_name.strip():
			frappe.throw("CRM Action display name is required.", frappe.ValidationError)
		if not self.purpose or not self.purpose.strip():
			frappe.throw("CRM Action purpose is required.", frappe.ValidationError)
		if self.sort_order is None:
			frappe.throw("CRM Action sort order is required.", frappe.ValidationError)
		try:
			validate_action_config(
				self.code,
				self.action_type,
				self.default_channel,
				self.allowed_actors,
				self.requires_approval,
				self.auto_execute,
				self.enabled,
				self.execution_type or "MANUAL",
				self.ai_allowed,
				self.allowed_time_slots,
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)


def get_permission_query_conditions(user=None):
	return None


def has_permission(doc, user=None, permission_type=None):
	return True
