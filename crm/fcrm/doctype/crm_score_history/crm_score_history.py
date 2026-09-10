import frappe
from frappe.model.document import Document


class CRMScoreHistory(Document):
	def before_insert(self):
		if not self.scoring_time:
			self.scoring_time = frappe.utils.now_datetime()

	def validate(self):
		self._set_score_change()

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
