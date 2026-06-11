import frappe
from frappe.model.document import Document


class CRMIntent(Document):
	def before_validate(self):
		if self.interaction and not self.student:
			self.student = frappe.db.get_value("CRM Interaction", self.interaction, "student")

		if self.intent_type and not self.importance:
			self.importance = frappe.db.get_value("CRM Intent Type", self.intent_type, "importance")

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Interaction",
				"type": "Link",
				"key": "interaction",
				"options": "CRM Interaction",
				"width": "14rem",
			},
			{
				"label": "Student",
				"type": "Link",
				"key": "student",
				"options": "CRM Student",
				"width": "14rem",
			},
			{
				"label": "Intent Type",
				"type": "Link",
				"key": "intent_type",
				"options": "CRM Intent Type",
				"width": "14rem",
			},
			{"label": "Importance", "type": "Select", "key": "importance", "width": "10rem"},
			{"label": "Confidence", "type": "Percent", "key": "confidence", "width": "8rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "interaction", "student", "intent_type", "importance", "confidence", "modified"]
		return {"columns": columns, "rows": rows}
