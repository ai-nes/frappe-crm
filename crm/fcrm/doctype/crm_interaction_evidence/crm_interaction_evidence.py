import frappe
from frappe.model.document import Document


class CRMInteractionEvidence(Document):
	"""Frappe-owned raw communication evidence.

	Interactions and AI results retain only this document's identity and digest;
	the raw body never propagates to those records.
	"""

	def validate(self):
		if not self.student and not self.crm_contact:
			frappe.throw("Evidence must be linked to a Student or CRM Contact.")
		if not self.content or not str(self.content).strip():
			frappe.throw("Evidence content is required.")
		if not self.evidence_digest or len(self.evidence_digest) != 64:
			frappe.throw("Evidence digest must be a SHA-256 digest.")
		if int(self.source_revision or 0) < 1:
			frappe.throw("Evidence source revision must be positive.")
		if self.evidence_kind not in {"message", "call"}:
			frappe.throw("Evidence kind is invalid.")
		if self.evidence_state not in {"draft", "final", "correction"}:
			frappe.throw("Evidence state is invalid.")
		if self.evidence_state == "draft" and self.evidence_kind != "call":
			frappe.throw("Only calls may be draft evidence.")

	def has_permission(self, ptype="read", user=None):
		"""Raw evidence is available only through the service capability.

		Target permissions continue to govern the surrounding CRM Interaction, but
		they intentionally do not grant a generic DocType read for its raw body.
		"""
		service_user = frappe.conf.get("crm_agents_service_user")
		return bool(service_user and (user or frappe.session.user) == service_user)
