import frappe
from frappe.model.document import Document


class CRMEventStreamCursor(Document):
	def validate(self):
		if not self.stream:
			frappe.throw("Event stream is required.")
		if not self.is_new() and self.has_value_changed("counter") and not frappe.flags.get("crm_event_stream_cursor_service"):
			frappe.throw("Event stream cursors may only be advanced by the event service.", frappe.PermissionError)
