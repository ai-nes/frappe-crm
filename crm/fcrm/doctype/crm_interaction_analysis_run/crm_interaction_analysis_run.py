import frappe
from frappe.model.document import Document


class CRMInteractionAnalysisRun(Document):
	"""Dedicated analysis lifecycle for one Interaction episode revision."""

	def validate(self):
		if not self.interaction or not self.episode_key:
			frappe.throw("Interaction analysis runs require an Interaction episode.")
		if int(self.source_revision or 0) < 1 or len(self.source_digest or "") != 64:
			frappe.throw("Interaction analysis run source revision and digest are invalid.")
		if self.status not in {"queued", "running", "completed", "abstained", "failed", "dead_lettered"}:
			frappe.throw("Interaction analysis run status is invalid.")
