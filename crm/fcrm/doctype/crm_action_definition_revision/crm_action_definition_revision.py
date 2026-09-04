import json

import frappe
from frappe.model.document import Document

from crm.fcrm.nba_canonical import canonical_digest


class CRMActionDefinitionRevision(Document):
	"""Immutable snapshot of one CRM Action definition at a point in time.

	Rows are written only from code with ``ignore_permissions`` when an Action's
	policy-relevant fields change; they are never edited or deleted afterwards,
	so the control plane can pin an exact definition by ``(action, revision)``.
	"""

	def validate(self):
		if not self.is_new():
			frappe.throw("Action Definition Revision rows are immutable.", frappe.ValidationError)
		snapshot = self.snapshot
		if isinstance(snapshot, str):
			try:
				snapshot = json.loads(snapshot)
			except json.JSONDecodeError:
				frappe.throw("Snapshot must be a JSON object.", frappe.ValidationError)
		if not isinstance(snapshot, dict):
			frappe.throw("Snapshot must be a JSON object.", frappe.ValidationError)
		if self.digest != canonical_digest(snapshot):
			frappe.throw("Digest does not bind the snapshot.", frappe.ValidationError)

	def on_trash(self):
		frappe.throw("Action Definition Revision rows are immutable.", frappe.ValidationError)
