import frappe
from frappe import _
from frappe.model.document import Document

from crm.fcrm.segment_code import generate_segment_code
from crm.fcrm.segment_lifecycle import validate_segment

SHARED_READ_ROLES = {"Lead Sale", "Sale", "CTV Sale"}


class CRMSegment(Document):
	def before_insert(self):
		self.segment_code = generate_segment_code(
			frappe.session.user or self.owner,
			frappe.utils.now_datetime(),
		)

	def before_save(self):
		before = self.get_doc_before_save()
		if before and before.get("segment_code") != self.get("segment_code"):
			frappe.throw(_("Segment Code is immutable after creation."), frappe.ValidationError)

	def validate(self):
		validate_segment(self)

	def before_rename(self, *args, **kwargs):
		frappe.throw("Segment identifiers are immutable.", frappe.PermissionError)

	def on_trash(self):
		if self.status != "draft":
			frappe.throw("Archive published segments instead of deleting them.")
		if frappe.db.exists(
			"CRM Marketing Engagement", {"engagement_kind": "campaign_touch", "crm_segment": self.name}
		):
			frappe.throw(
				frappe._(
					"This Segment cannot be deleted because it has marketing engagement records "
					"attached to it. Remove those references first."
				)
			)

	@staticmethod
	def default_list_data():
		columns = [
			{"label": "Segment Code", "type": "Data", "key": "segment_code", "width": "16rem"},
			{"label": "Title", "type": "Data", "key": "title", "width": "16rem"},
			{"label": "Public", "type": "Check", "key": "is_public", "width": "6rem"},
			{"label": "Owner", "type": "Link", "key": "owner", "options": "User", "width": "12rem"},
			{"label": "Last Modified", "type": "Datetime", "key": "modified", "width": "8rem"},
		]
		rows = ["name", "segment_code", "title", "is_public", "owner", "modified"]
		return {"columns": columns, "rows": rows}


def get_permission_query_conditions(user=None):
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return ""
	if SHARED_READ_ROLES.intersection(frappe.get_roles(user)):
		return ""
	return f"""(`tabCRM Segment`.`is_public` = 1 OR `tabCRM Segment`.`owner` = {frappe.db.escape(user)})"""


def has_permission(doc, user=None, permission_type=None, ptype=None):
	permission_type = permission_type or ptype or "read"
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	if permission_type == "read" and SHARED_READ_ROLES.intersection(frappe.get_roles(user)):
		return True
	if doc.owner == user:
		return True
	# For roles outside the shared segment audience, is_public only grants
	# visibility (read), never write/delete/share on someone else's segment.
	if doc.is_public and permission_type in (None, "read"):
		return True
	return False
