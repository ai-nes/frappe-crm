import re

import frappe
from frappe import _
from frappe.model.document import Document


class CRMSnippet(Document):
	"""Reusable short content owned by the user who created it."""

	def validate(self):
		self.internal_name = str(self.internal_name or "").strip()
		self.shortcut = _normalize_shortcut(self.shortcut)
		if not self.internal_name:
			frappe.throw(_("Internal name is required."), frappe.ValidationError)
		if not _has_content(self.snippet_text):
			frappe.throw(_("Snippet text is required."), frappe.ValidationError)
		self._validate_shortcut_is_unique()

	def before_insert(self):
		self.internal_name = str(self.internal_name or "").strip()
		self.shortcut = _normalize_shortcut(self.shortcut)
		self.is_public = 1 if frappe.utils.cint(self.is_public) else 0

	def _validate_shortcut_is_unique(self):
		name = frappe.db.get_value("CRM Snippet", {"shortcut": self.shortcut}, "name")
		if name and name != self.name:
			frappe.throw(_("Shortcut must be unique."), frappe.ValidationError)


def _normalize_shortcut(value):
	shortcut = str(value or "").strip().lstrip("#").strip()
	if not shortcut:
		frappe.throw(_("Shortcut is required."), frappe.ValidationError)
	if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", shortcut):
		frappe.throw(
			_("Shortcut may contain only letters, numbers, dots, underscores, and hyphens."),
			frappe.ValidationError,
		)
	return shortcut


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
