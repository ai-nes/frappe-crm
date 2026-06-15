import frappe
from frappe import _
from frappe.model.document import Document


class CRMIntent(Document):
	def before_validate(self):
		if self.interaction and not self.student:
			self.student = frappe.db.get_value("CRM Interaction", self.interaction, "student")

		if self.intent_type and not self.importance:
			self.importance = frappe.db.get_value("CRM Intent Type", self.intent_type, "importance")

	def validate(self):
		if self.intent_role == "Dominant" and self.interaction:
			filters = {"interaction": self.interaction, "intent_role": "Dominant"}
			if not self.is_new():
				filters["name"] = ["!=", self.name]
			existing = frappe.db.get_value("CRM Intent", filters, "name")
			if existing:
				frappe.throw(
					_("Interaction {0} already has a Dominant intent ({1}). Only one Dominant intent is allowed per interaction.").format(
						self.interaction, existing
					)
				)

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
			{"label": "Role", "type": "Select", "key": "intent_role", "width": "8rem"},
			{"label": "Importance", "type": "Select", "key": "importance", "width": "10rem"},
			{"label": "Confidence", "type": "Percent", "key": "confidence", "width": "8rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "interaction", "student", "intent_type", "intent_role", "importance", "confidence", "modified"]
		return {"columns": columns, "rows": rows}
