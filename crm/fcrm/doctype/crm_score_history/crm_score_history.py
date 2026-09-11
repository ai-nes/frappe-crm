import frappe
from frappe.model.document import Document

from crm.services.score_revision import normalize_score_ruleset_identity


class CRMScoreHistory(Document):
	def before_insert(self):
		if not self.scoring_time:
			self.scoring_time = frappe.utils.now_datetime()

	def validate(self):
		try:
			normalize_score_ruleset_identity(
				{
					"rule_version": self.get("rule_version"),
					"rule_version_digest": self.get("rule_version_digest"),
					"ruleset_digest": self.get("ruleset_digest"),
				},
				allow_empty=True,
			)
		except ValueError as exc:
			frappe.throw(str(exc), frappe.ValidationError)
		self._set_score_change()

	def on_update(self):
		frappe.db.set_value(
			"CRM Student",
			self.student,
			"latest_score",
			self.final_score or 0,
			update_modified=False,
		)

	def _set_score_change(self):
		if self.score_change is not None:
			return

		previous_score = frappe.db.get_value(
			"CRM Score History",
			{
				"student": self.student,
				"name": ["!=", self.name],
			},
			"final_score",
			order_by="scoring_time desc, creation desc",
		)
		self.score_change = (self.final_score or 0) - (previous_score or 0)
