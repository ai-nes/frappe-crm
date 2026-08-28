import frappe
from frappe.model.document import Document

from crm.fcrm.student_contact_conversion import contact_is_linked_to_student


class CRMCampaignTouchpoint(Document):
	def before_validate(self):
		if (
			self.is_new()
			and not getattr(frappe.flags, "student_attribution_service", False)
			and not getattr(frappe.flags, "in_test", False)
		):
			frappe.throw("Campaign attribution must be recorded through the Student attribution command.", frappe.PermissionError)
		if not self.touched_at:
			self.touched_at = frappe.utils.now_datetime()

	def validate(self):
		if not self.is_new() and not getattr(frappe.flags, "in_test", False):
			frappe.throw("Campaign attribution evidence is append-only; create a superseding correction instead.", frappe.PermissionError)
		if not self.student:
			frappe.throw("Student is required for new attribution evidence.")
		if self.crm_contact and not contact_is_linked_to_student(self.crm_contact, self.student):
			frappe.throw("CRM Contact must belong to the evidence Student.")

	def on_trash(self):
		if not getattr(frappe.flags, "in_test", False):
			frappe.throw("Campaign attribution evidence is append-only and cannot be deleted.", frappe.PermissionError)

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
