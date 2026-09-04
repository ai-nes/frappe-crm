"""CRUD API for FCRM Note, scoped to CRM Student / CRM Contact.

FCRM Note itself carries only global role permissions (no
permission_query_conditions/has_permission hook), so a plain
frappe.client.insert/delete on it is not scoped by student/contact
ownership. Every entry point here re-checks permission on the referenced
CRM Student or CRM Contact first, so a note is only readable/writable by
someone who can already see that student/contact.
"""

import frappe
from frappe import _

from crm.api._pagination import paged_list

ALLOWED_REFERENCE_DOCTYPES = {"CRM Student", "CRM Contact"}

FIELDS = ["name", "content", "reference_doctype", "reference_docname", "owner", "creation", "modified"]


def _check_reference_access(reference_doctype, reference_docname, permission_type):
	if reference_doctype not in ALLOWED_REFERENCE_DOCTYPES:
		frappe.throw(_("Notes are only supported for CRM Student and CRM Contact."), frappe.ValidationError)
	reference_doc = frappe.get_doc(reference_doctype, reference_docname)
	reference_doc.check_permission(permission_type)
	return reference_doc


def _with_owner_full_name(note):
	as_dict = getattr(note, "as_dict", None)
	data = as_dict() if callable(as_dict) else dict(note)
	data["owner_full_name"] = (
		frappe.get_cached_value("User", data.get("owner"), "full_name") if data.get("owner") else None
	)
	return data


@frappe.whitelist()
def list_notes(reference_doctype, reference_docname, search=None, start=0, page_length=20):
	"""List FCRM Notes attached to one CRM Student or CRM Contact.

	Requires read access to that student/contact. Optional search matches content.
	"""
	_check_reference_access(reference_doctype, reference_docname, "read")

	filters = {"reference_doctype": reference_doctype, "reference_docname": reference_docname}
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [["content", "like", like]]

	result = paged_list(
		"FCRM Note",
		FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="modified desc",
	)
	rows = [_with_owner_full_name(row) for row in result.pop("rows")]
	return {**result, "notes": rows}


@frappe.whitelist()
def get_note(name):
	"""Get one FCRM Note. Requires read access to its referenced student/contact."""
	doc = frappe.get_doc("FCRM Note", name)
	doc.check_permission("read")
	_check_reference_access(doc.reference_doctype, doc.reference_docname, "read")
	return _with_owner_full_name(doc)


@frappe.whitelist(methods=["POST"])
def create_note(reference_doctype, reference_docname, content=None):
	"""Create an FCRM Note on a CRM Student or CRM Contact. Requires read
	access to that student/contact and create access to FCRM Note.
	"""
	_check_reference_access(reference_doctype, reference_docname, "read")
	doc = frappe.new_doc("FCRM Note")
	doc.content = content
	doc.reference_doctype = reference_doctype
	doc.reference_docname = reference_docname
	doc.insert()
	return _with_owner_full_name(doc)


@frappe.whitelist(methods=["POST", "PUT"])
def update_note(name, content=None):
	"""Update an FCRM Note's content. The reference is fixed at creation.

	Requires read access to the referenced student/contact and write access to
	FCRM Note.
	"""
	doc = frappe.get_doc("FCRM Note", name)
	doc.check_permission("write")
	_check_reference_access(doc.reference_doctype, doc.reference_docname, "read")
	if content is not None:
		doc.content = content
	doc.save()
	return _with_owner_full_name(doc)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_note(name):
	"""Delete an FCRM Note. Requires delete access on the note and read access
	to the referenced student/contact.
	"""
	doc = frappe.get_doc("FCRM Note", name)
	doc.check_permission("delete")
	_check_reference_access(doc.reference_doctype, doc.reference_docname, "read")
	doc.delete()
	return {"deleted": name}
