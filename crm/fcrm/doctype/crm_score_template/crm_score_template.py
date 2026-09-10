import frappe
from frappe.model.document import Document
from frappe.utils import get_datetime

from crm.fcrm.scoring_policy import sync_policy_revision


class CRMScoreTemplate(Document):
	def validate(self):
		if self.start_time and self.end_time and get_datetime(self.end_time) <= get_datetime(self.start_time):
			frappe.throw("Score Template end time must be after its start time.")
		if self.status == "Active":
			existing = frappe.db.get_value(
				"CRM Score Template",
				{"status": "Active", "name": ("!=", self.name)},
				"name",
			)
			if existing:
				frappe.throw(
					f"Only one Score Template can be Active at a time. Please deactivate <b>{existing}</b> first."
				)

	def before_save(self):
		sync_policy_revision(self)

	def on_update(self):
		"""Re-score the active cohort when the active policy changes."""
		before = self.get_doc_before_save()
		was_active = bool(before and before.status == "Active")
		if self.status != "Active":
			return
		before_revision = int(before.policy_revision or 0) if before else None
		after_revision = int(self.policy_revision or 0)
		if was_active and before_revision == after_revision:
			return
		frappe.enqueue(
			"crm.fcrm.scoring_run.score_active_cohort",
			queue="long",
			enqueue_after_commit=True,
		)
