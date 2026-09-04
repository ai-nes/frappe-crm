import json

import frappe
from frappe.model.document import Document

CHANNELS = {"NONE", "CALL", "EMAIL", "MESSAGE"}
ACTOR_ROLES = {"Sale", "Lead Sales", "Marketing", "Promoter", "Admissions Director", "System Manager"}


class CRMActionDefinition(Document):
	"""Configured action definition; instances live in CRM Action."""

	def validate(self):
		if self.default_channel not in CHANNELS:
			frappe.throw("Invalid NBA default channel.", frappe.ValidationError)
		try:
			actors = (
				json.loads(self.allowed_actors)
				if isinstance(self.allowed_actors, str)
				else self.allowed_actors
			)
		except (TypeError, ValueError):
			frappe.throw("Allowed actors must be a JSON array.", frappe.ValidationError)
		if not isinstance(actors, list) or not actors or any(actor not in ACTOR_ROLES for actor in actors):
			frappe.throw("Allowed actors must contain only canonical CRM roles.", frappe.ValidationError)
		if self.requires_approval and self.auto_execute:
			frappe.throw(
				"An Action Definition cannot require approval and auto-execute at the same time.",
				frappe.ValidationError,
			)
