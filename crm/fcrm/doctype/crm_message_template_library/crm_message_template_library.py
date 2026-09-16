import re

import frappe
from frappe import _
from frappe.model.document import Document


class CRMMessageTemplateLibrary(Document):
	"""Admin-managed email templates available to users when creating a template."""

	def validate(self):
		if not str(self.template_name or "").strip():
			frappe.throw(_("Template name is required."), frappe.ValidationError)
		if not str(self.category or "").strip():
			frappe.throw(_("Template category is required."), frappe.ValidationError)
		if not str(self.subject or "").strip():
			frappe.throw(_("Template subject is required."), frappe.ValidationError)
		if not _has_body_content(self.body):
			frappe.throw(_("Template body is required."), frappe.ValidationError)

	def before_insert(self):
		self.template_name = str(self.template_name or "").strip()
		self.category = str(self.category or "").strip()
		self.subject = str(self.subject or "").strip()
		self.is_active = 1 if frappe.utils.cint(self.is_active) else 0


def _has_body_content(value):
	text = re.sub(r"<[^>]*>", "", str(value or ""))
	text = text.replace("&nbsp;", " ")
	return bool(text and text.strip())


def get_permission_query_conditions(user=None):
	actor = user or frappe.session.user
	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return ""
	if actor == "Guest":
		return "1=0"
	return "`tabCRM Message Template Library`.`is_active` = 1"


def has_permission(doc, user=None, permission_type=None, ptype=None):
	if not doc:
		return None
	permission_type = permission_type or ptype or "read"
	actor = user or frappe.session.user
	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return True
	if actor == "Guest":
		return False
	return permission_type == "read" and bool(frappe.utils.cint(doc.is_active))
