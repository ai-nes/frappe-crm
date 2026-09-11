import re

import frappe
from frappe import _
from frappe.model.document import Document


class CRMSnippet(Document):
	"""Reusable short content owned by the user who created it."""

	def validate(self):
		if not str(self.snippet_name or "").strip():
			frappe.throw(_("Snippet name is required."), frappe.ValidationError)
		if not _has_content(self.content):
			frappe.throw(_("Snippet content is required."), frappe.ValidationError)

	def before_insert(self):
		self.snippet_name = str(self.snippet_name or "").strip()
		self.is_public = 1 if frappe.utils.cint(self.is_public) else 0


def _has_content(value):
	text = re.sub(r"<[^>]*>", "", str(value or ""))
	text = text.replace("&nbsp;", " ")
	return bool(text and text.strip())


def get_permission_query_conditions(user=None):
	actor = user or frappe.session.user
	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return ""
	if actor == "Guest":
		return "1=0"
	return f"(`tabCRM Snippet`.`is_public` = 1 OR `tabCRM Snippet`.`owner` = {frappe.db.escape(actor)})"


def has_permission(doc, user=None, permission_type=None, ptype=None):
	if not doc:
		return None
	permission_type = permission_type or ptype or "read"
	actor = user or frappe.session.user
	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return True
	if actor == "Guest":
		return False
	if doc.owner == actor:
		return True
	return bool(frappe.utils.cint(doc.is_public) and permission_type == "read")
