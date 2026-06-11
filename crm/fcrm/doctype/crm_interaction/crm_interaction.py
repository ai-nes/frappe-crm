import frappe
from frappe.model.document import Document


class CRMInteraction(Document):
	def before_validate(self):
		if not self.interaction_datetime:
			self.interaction_datetime = frappe.utils.now_datetime()

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Student",
				"type": "Link",
				"key": "student",
				"options": "CRM Student",
				"width": "14rem",
			},
			{
				"label": "Contact",
				"type": "Link",
				"key": "crm_contact",
				"options": "CRM Contact",
				"width": "14rem",
			},
			{
				"label": "Interaction Type",
				"type": "Link",
				"key": "interaction_type",
				"options": "CRM Interaction Type",
				"width": "12rem",
			},
			{
				"label": "Interaction Time",
				"type": "Datetime",
				"key": "interaction_datetime",
				"width": "12rem",
			},
			{"label": "Outcome", "type": "Select", "key": "outcome", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = [
			"name",
			"student",
			"crm_contact",
			"interaction_type",
			"interaction_datetime",
			"summary",
			"outcome",
			"modified",
		]
		return {"columns": columns, "rows": rows}
