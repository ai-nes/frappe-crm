from frappe.model.document import Document


class CRMParentContactAuthority(Document):
	"""Append-only authorization evidence for Parent Contact actions."""

	def validate(self):
		if self.revoked_at and not self.revocation_evidence:
			raise ValueError("revocation evidence is required")
