import frappe
from frappe import _


def block_parent_change_if_has_children(doc, child_doctype, child_link_field, parent_field):
	"""Refuse to change `doc`'s `parent_field` once child rows already point at it."""
	if doc.is_new():
		return
	previous = doc.get_doc_before_save()
	if not previous or previous.get(parent_field) == doc.get(parent_field):
		return
	if frappe.db.exists(child_doctype, {child_link_field: doc.name}):
		frappe.throw(
			_("Cannot change {0}: this {1} already has {2} under it.").format(
				doc.meta.get_field(parent_field).label, doc.doctype, child_doctype
			),
			frappe.ValidationError,
		)


def block_delete_if_has_children(doc, child_doctype, child_link_field, message=None):
	"""Refuse to delete `doc` while child rows still reference it."""
	if frappe.db.exists(child_doctype, {child_link_field: doc.name}):
		frappe.throw(
			message
			or _("Cannot delete {0} {1}: it still has {2} under it.").format(
				doc.doctype, doc.name, child_doctype
			),
			frappe.ValidationError,
		)
