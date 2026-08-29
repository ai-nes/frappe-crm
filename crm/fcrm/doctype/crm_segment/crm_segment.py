import frappe
from frappe.model.document import Document

from crm.api.segment import validate_segment_filters


class CRMSegment(Document):
	def validate(self):
		self.filters = validate_segment_filters(self.filters)

	def on_trash(self):
		if frappe.db.exists("CRM Marketing Engagement", {"engagement_kind": "campaign_touch", "crm_segment": self.name}):
			frappe.throw(
				frappe._(
				"This Segment cannot be deleted because it has marketing engagement records "
					"attached to it. Remove those references first."
				)
			)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Title", "type": "Data", "key": "title", "width": "16rem"},
			{"label": "Public", "type": "Check", "key": "is_public", "width": "6rem"},
			{"label": "Owner", "type": "Link", "key": "owner", "options": "User", "width": "12rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "title", "is_public", "owner", "modified"]
		return {"columns": columns, "rows": rows}


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	return f"""(`tabCRM Segment`.`is_public` = 1 OR `tabCRM Segment`.`owner` = {frappe.db.escape(user)})"""


def has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	if doc.owner == user:
		return True
	# is_public only grants visibility (read), never write/delete/share on
	# someone else's segment.
	if doc.is_public and permission_type in (None, "read"):
		return True
	return False
