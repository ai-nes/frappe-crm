import frappe
from frappe.model.document import Document


class CRMCampaign(Document):
	def before_insert(self):
		if not self.owner_staff:
			self.owner_staff = frappe.db.get_value("CRM Staff", {"user": frappe.session.user}, "name")

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Title", "type": "Data", "key": "title", "width": "16rem"},
			{"label": "Campus", "type": "Link", "key": "campus", "options": "CRM Campus", "width": "12rem"},
			{"label": "Campaign Type", "type": "Link", "key": "campaign_type", "options": "CRM Campaign Type", "width": "12rem"},
			{"label": "Status", "type": "Select", "key": "status", "width": "8rem"},
			{"label": "Owner", "type": "Link", "key": "owner_staff", "options": "CRM Staff", "width": "10rem"},
			{"label": "Start Date", "type": "Date", "key": "start_date", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "title", "campus", "campaign_type", "status", "owner_staff", "start_date", "modified"]
		return {"columns": columns, "rows": rows}
