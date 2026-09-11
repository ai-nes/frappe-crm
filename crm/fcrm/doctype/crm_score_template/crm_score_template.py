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
