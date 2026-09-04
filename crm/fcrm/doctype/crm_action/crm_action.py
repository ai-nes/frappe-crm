import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from crm.fcrm.action_constraints import validate_action_config
from crm.fcrm.action_type_catalog import ACTION_TYPE_METADATA, is_valid_configuration_code
from crm.fcrm.nba_canonical import action_definition_snapshot, canonical_digest


class CRMAction(Document):
	"""Master row for a built-in or custom CRM Action."""

	def validate(self):
		if not is_valid_configuration_code(self.code):
			frappe.throw(
				"CRM Action code must contain only uppercase letters, numbers, and underscores.",
				frappe.ValidationError,
			)
		metadata = ACTION_TYPE_METADATA.get(self.code)
		if metadata and self.action_type != metadata["category"]:
			frappe.throw(
				f"CRM Action {self.code} must use Action Type {metadata['category']}.",
				frappe.ValidationError,
			)
		if not self.action_type or not frappe.db.exists("CRM Action Type", self.action_type):
			frappe.throw("CRM Action Type must exist before creating an Action.", frappe.ValidationError)
		if frappe.utils.cint(self.enabled) and not frappe.utils.cint(
			frappe.db.get_value("CRM Action Type", self.action_type, "enabled")
		):
			frappe.throw(
				"CRM Action Type must be enabled before enabling an Action.",
				frappe.ValidationError,
			)
		if not self.display_name or not self.display_name.strip():
			frappe.throw("CRM Action display name is required.", frappe.ValidationError)
		if not self.purpose or not self.purpose.strip():
			frappe.throw("CRM Action purpose is required.", frappe.ValidationError)
		if self.sort_order is None:
			frappe.throw("CRM Action sort order is required.", frappe.ValidationError)
		if (
			self.effective_from
			and self.effective_to
			and get_datetime(self.effective_to) <= get_datetime(self.effective_from)
		):
			frappe.throw("effective_to must be after effective_from.", frappe.ValidationError)
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
				allow_custom=True,
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)

	def on_trash(self):
		if _has_references(self.code):
			frappe.throw(
				"CRM Action cannot be deleted while it is referenced by CRM records. Disable it instead.",
				frappe.ValidationError,
			)

	def _snapshot(self) -> dict:
		row = self.as_dict()
		row["category"] = ACTION_TYPE_METADATA[self.code]["category"]
		return action_definition_snapshot(row)

	def sync_definition_revision(self) -> bool:
		"""Recompute the definition snapshot; on a change, bump revision and log it.

		Returns whether a new revision was written. Nothing calls this on save
		yet -- the control-plane patch owns the first population.
		"""
		snapshot = self._snapshot()
		digest = canonical_digest(snapshot)
		if digest == (self.definition_digest or ""):
			return False
		self.definition_digest = digest
		self.definition_revision = int(self.definition_revision or 0) + 1
		frappe.get_doc(
			{
				"doctype": "CRM Action Definition Revision",
				"action": self.name,
				"revision": self.definition_revision,
				"digest": digest,
				"snapshot": snapshot,
				"created_at": now_datetime(),
			}
		).insert(ignore_permissions=True)
		return True


def get_permission_query_conditions(user=None):
	return None


def has_permission(doc, user=None, permission_type=None):
	return True


def _has_references(code: str) -> bool:
	for doctype, fieldname in (
		("CRM Action Item", "action"),
		("CRM Recommendation", "action"),
		("CRM Recommendation Rule", "action"),
	):
		if frappe.db.exists("DocType", doctype) and frappe.db.exists(doctype, {fieldname: code}):
			return True
	return False
