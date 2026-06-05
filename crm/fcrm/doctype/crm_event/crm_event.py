from frappe.model.document import Document


class CRMEvent(Document):
	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Title", "type": "Data", "key": "title", "width": "16rem"},
			{"label": "Campaign", "type": "Link", "key": "crm_campaign", "options": "CRM Campaign", "width": "12rem"},
			{"label": "Province", "type": "Link", "key": "province", "options": "CRM Province", "width": "12rem"},
			{"label": "Event Date", "type": "Date", "key": "event_date", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "title", "crm_campaign", "province", "event_date", "modified"]
		return {"columns": columns, "rows": rows}
