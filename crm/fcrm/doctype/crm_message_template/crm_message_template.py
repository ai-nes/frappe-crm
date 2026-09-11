import re

import frappe
from frappe import _
from frappe.model.document import Document


class CRMMessageTemplate(Document):
	"""Reusable email wording owned by the user who created it."""

	def validate(self):
		if not str(self.template_name or "").strip():
			frappe.throw(_("Template name is required."), frappe.ValidationError)
		if not str(self.subject or "").strip():
			frappe.throw(_("Template subject is required."), frappe.ValidationError)
		if not _has_body_content(self.body):
			frappe.throw(_("Template body is required."), frappe.ValidationError)

	def before_insert(self):
		self.template_name = str(self.template_name or "").strip()
		self.subject = str(self.subject or "").strip()
		self.is_public = 1 if frappe.utils.cint(self.is_public) else 0


def _has_body_content(value):
	text = re.sub(r"<[^>]*>", "", str(value or ""))
	text = text.replace("&nbsp;", " ")
	return bool(text and text.strip())


def get_permission_query_conditions(user=None):
	actor = user or frappe.session.user
	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return ""
	return (
		f"(`tabCRM Message Template`.`is_public` = 1 "
		f"OR `tabCRM Message Template`.`owner` = {frappe.db.escape(actor)})"
	)


def has_permission(doc, user=None, permission_type=None, ptype=None):
	if not doc:
		return None
	permission_type = permission_type or ptype or "read"
	actor = user or frappe.session.user
	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return True
	if doc.owner == actor:
		return True
	# Public templates are readable by eligible role holders, but remain owned rows.
	return bool(frappe.utils.cint(doc.is_public) and permission_type == "read")
