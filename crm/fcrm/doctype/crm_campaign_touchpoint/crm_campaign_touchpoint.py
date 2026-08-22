import frappe
from frappe.model.document import Document


class CRMCampaignTouchpoint(Document):
	def before_validate(self):
		if not self.student and self.crm_contact:
			self.student = frappe.db.get_value("CRM Contact", self.crm_contact, "student")
		if not self.touched_at:
			self.touched_at = frappe.utils.now_datetime()

	def validate(self):
		if self.is_new() and frappe.db.exists(
			"CRM Campaign Touchpoint", {"crm_campaign": self.crm_campaign, "crm_contact": self.crm_contact}
		):
			frappe.throw(
				frappe._("This contact already has a touchpoint recorded for this campaign.")
			)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Campaign", "type": "Link", "key": "crm_campaign", "options": "CRM Campaign", "width": "14rem"},
			{"label": "Contact", "type": "Link", "key": "crm_contact", "options": "CRM Contact", "width": "14rem"},
			{"label": "Touched At", "type": "Datetime", "key": "touched_at", "width": "10rem"},
			{"label": "Source", "type": "Select", "key": "source", "width": "8rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "crm_campaign", "crm_contact", "touched_at", "source", "modified"]
		return {"columns": columns, "rows": rows}
