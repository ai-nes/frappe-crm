import frappe
from frappe.model.document import Document

from crm.fcrm.student_contact_conversion import contact_is_linked_to_student


class CRMMarketingEngagement(Document):
	def before_validate(self):
		if (
			self.is_new()
			and not getattr(frappe.flags, "student_attribution_service", False)
			and not getattr(frappe.flags, "student_attribution_migration", False)
			and not getattr(frappe.flags, "in_test", False)
		):
			frappe.throw("Marketing engagement must be recorded through the Student attribution command.", frappe.PermissionError)
		if self.engagement_kind == "event_participation":
			if not self.actor:
				self.actor = frappe.session.user
			if self.is_new() and not self.registered_at:
				self.registered_at = frappe.utils.now_datetime()
			if self.status == "Checked-in" and not self.checked_in_at:
				self.checked_in_at = frappe.utils.now_datetime()
		elif self.is_new() and not self.touched_at:
			self.touched_at = frappe.utils.now_datetime()

	def validate(self):
		if not self.engagement_kind:
			frappe.throw("Engagement kind is required.")
		if not self.is_new() and not getattr(frappe.flags, "in_test", False):
			frappe.throw("Marketing engagement evidence is append-only; create a superseding correction instead.", frappe.PermissionError)
		if not self.student:
			frappe.throw("Student is required for new attribution evidence.")
		if self.crm_contact and not contact_is_linked_to_student(self.crm_contact, self.student):
			frappe.throw("CRM Contact must belong to the evidence Student.")
		if self.engagement_kind == "campaign_touch":
			if self.reference_doctype != "CRM Campaign" or not self.reference_name or not self.crm_campaign:
				frappe.throw("Campaign engagement requires a campaign reference.")
			if not self.touched_at:
				frappe.throw("Campaign engagement requires touched_at.")
		elif self.engagement_kind == "event_participation":
			if self.reference_doctype != "CRM Event" or not self.reference_name or not self.crm_event:
				frappe.throw("Event engagement requires an event reference.")
			if not self.status:
				frappe.throw("Event engagement requires status.")
			if self.is_new() and not self.supersedes and frappe.db.exists(
				"CRM Marketing Engagement",
				{"engagement_kind": "event_participation", "crm_event": self.crm_event, "crm_contact": self.crm_contact, "student": self.student},
			):
				frappe.throw("This contact already has a participation record for this event.")
		else:
			frappe.throw("Unsupported engagement kind.")

	def on_trash(self):
		if not getattr(frappe.flags, "in_test", False):
			frappe.throw("Marketing engagement evidence is append-only and cannot be deleted.", frappe.PermissionError)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Kind", "type": "Select", "key": "engagement_kind", "width": "10rem"},
			{"label": "Campaign", "type": "Link", "key": "crm_campaign", "options": "CRM Campaign", "width": "14rem"},
			{"label": "Event", "type": "Link", "key": "crm_event", "options": "CRM Event", "width": "14rem"},
			{"label": "Contact", "type": "Link", "key": "crm_contact", "options": "CRM Contact", "width": "14rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "engagement_kind", "crm_campaign", "crm_event", "crm_contact", "status", "touched_at", "registered_at", "modified"]
		return {"columns": columns, "rows": rows}
