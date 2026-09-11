import json

import frappe
from frappe.model.document import Document

from crm.services.score_revision import RULESET_IDENTITY_FIELDS, normalize_score_ruleset_identity


class CRMAgentEvent(Document):
	"""Immutable delivery record for the crm-agents transactional outbox."""

	def validate(self):
		if self.event_type != "student.score_input_changed.v1":
			return
		try:
			identity = normalize_score_ruleset_identity(
				{field: self.get(field) for field in RULESET_IDENTITY_FIELDS}
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)
		try:
			payload = json.loads(self.payload or "")
		except (TypeError, ValueError):
			frappe.throw("Score input event payload must be valid JSON.", frappe.ValidationError)
		if not isinstance(payload, dict) or set(payload) != set(RULESET_IDENTITY_FIELDS):
			frappe.throw("Score input event payload must contain identity fields only.", frappe.ValidationError)
		try:
			payload_identity = normalize_score_ruleset_identity(payload)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)
		if payload_identity != identity:
			frappe.throw("Score input event payload identity does not match its fields.", frappe.ValidationError)
