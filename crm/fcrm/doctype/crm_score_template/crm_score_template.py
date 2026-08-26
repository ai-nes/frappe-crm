import frappe
from frappe.model.document import Document

from crm.fcrm.scoring_policy import sync_policy_revision


class CRMScoreTemplate(Document):
	def validate(self):
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
		"""Notify crm-agents when the Active template's policy actually changed.

		Without this, crm-agents' hour-long template cache (Settings.
		SCORE_TEMPLATE_CACHE_TTL_S) can serve a stale policy_revision to any
		fact event that arrives inside that window, and a student with no
		later fact change would stay stale until the next batch cron. Only fires
		for the currently Active template, and only when policy_revision
		actually moved -- a no-op save must not trigger a cohort rescore.
		"""
		if self.status != "Active":
			return
		before = self.get_doc_before_save()
		before_revision = int(before.policy_revision or 0) if before else None
		after_revision = int(self.policy_revision or 0)
		if before_revision == after_revision:
			return
		from crm.api.agent_events import record_agent_event

		record_agent_event("scoring.policy_changed.v1", self)
