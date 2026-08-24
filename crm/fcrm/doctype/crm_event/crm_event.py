import frappe
from frappe.model.document import Document


class CRMEvent(Document):
	def before_insert(self):
		if not self.owner_staff:
			self.owner_staff = frappe.db.get_value("CRM Staff", {"user": frappe.session.user}, "name")
		if not self.start_datetime and self.event_date:
			self.start_datetime = self.event_date

	def validate(self):
		# event_date is deprecated but kept populated for backward-compatible
		# readers (reports/patches) that haven't moved to start_datetime yet.
		if self.start_datetime:
			self.event_date = frappe.utils.getdate(self.start_datetime)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Title", "type": "Data", "key": "title", "width": "16rem"},
			{"label": "Campaign", "type": "Link", "key": "crm_campaign", "options": "CRM Campaign", "width": "12rem"},
			{"label": "Province", "type": "Link", "key": "province", "options": "CRM Province", "width": "12rem"},
			{"label": "Owner", "type": "Link", "key": "owner_staff", "options": "CRM Staff", "width": "10rem"},
			{"label": "Start Time", "type": "Datetime", "key": "start_datetime", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "title", "crm_campaign", "province", "owner_staff", "start_datetime", "modified"]
		return {"columns": columns, "rows": rows}
