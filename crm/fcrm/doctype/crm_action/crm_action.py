import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime, now_datetime

from crm.fcrm.action_type_catalog import ACTION_TYPE_CODES, ACTION_TYPE_METADATA
from crm.fcrm.nba_canonical import action_definition_snapshot, canonical_digest


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
		if (
			self.effective_from
			and self.effective_to
			and get_datetime(self.effective_to) <= get_datetime(self.effective_from)
		):
			frappe.throw("effective_to must be after effective_from.", frappe.ValidationError)

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
