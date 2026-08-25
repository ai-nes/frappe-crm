import frappe
from frappe.model.document import Document

from crm.fcrm.student_contact_conversion import contact_is_linked_to_student


class CRMEventParticipation(Document):
	def before_validate(self):
		if self.is_new() and not getattr(frappe.flags, "student_attribution_service", False):
			frappe.throw("Event attribution must be recorded through the Student attribution command.", frappe.PermissionError)
		if self.is_new() and not self.registered_at:
			self.registered_at = frappe.utils.now_datetime()
		if self.status == "Checked-in" and not self.checked_in_at:
			self.checked_in_at = frappe.utils.now_datetime()

	def validate(self):
		if not self.is_new():
			frappe.throw("Event attribution evidence is append-only; create a superseding correction instead.", frappe.PermissionError)
		if not self.student:
			frappe.throw("Student is required for new attribution evidence.")
		if self.crm_contact and not contact_is_linked_to_student(self.crm_contact, self.student):
			frappe.throw("CRM Contact must belong to the evidence Student.")

	def on_trash(self):
		frappe.throw("Event attribution evidence is append-only and cannot be deleted.", frappe.PermissionError)

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
