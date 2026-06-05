from frappe.model.document import Document


class CRMCampaign(Document):
	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Title", "type": "Data", "key": "title", "width": "16rem"},
			{"label": "Campus", "type": "Link", "key": "campus", "options": "CRM Campus", "width": "12rem"},
			{"label": "Campaign Type", "type": "Link", "key": "campaign_type", "options": "CRM Campaign Type", "width": "12rem"},
			{"label": "Start Date", "type": "Date", "key": "start_date", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "title", "campus", "campaign_type", "start_date", "modified"]
		return {"columns": columns, "rows": rows}
