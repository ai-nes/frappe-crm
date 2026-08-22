import frappe
from frappe.model.document import Document


class CRMEventParticipation(Document):
	def before_validate(self):
		if not self.student and self.crm_contact:
			self.student = frappe.db.get_value("CRM Contact", self.crm_contact, "student")
		if not self.actor:
			self.actor = frappe.session.user
		if self.is_new() and not self.registered_at:
			self.registered_at = frappe.utils.now_datetime()
		if self.status == "Checked-in" and not self.checked_in_at:
			self.checked_in_at = frappe.utils.now_datetime()

	def validate(self):
		if self.is_new() and frappe.db.exists(
			"CRM Event Participation", {"crm_event": self.crm_event, "crm_contact": self.crm_contact}
		):
			frappe.throw(
				frappe._("This contact already has a participation record for this event -- update it instead of creating a duplicate.")
			)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Event", "type": "Link", "key": "crm_event", "options": "CRM Event", "width": "14rem"},
			{"label": "Contact", "type": "Link", "key": "crm_contact", "options": "CRM Contact", "width": "14rem"},
			{"label": "Status", "type": "Select", "key": "status", "width": "10rem"},
			{"label": "Registered At", "type": "Datetime", "key": "registered_at", "width": "10rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "crm_event", "crm_contact", "status", "registered_at", "modified"]
		return {"columns": columns, "rows": rows}
