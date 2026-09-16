"""CRUD API for FCRM Note, scoped to CRM Student with Lead compatibility.

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
from crm.fcrm.lead_identity import resolve_lead_name
from crm.fcrm.student_reference import canonical_student

ALLOWED_REFERENCE_DOCTYPES = {"CRM Lead", "CRM Student"}

FIELDS = ["name", "content", "reference_doctype", "reference_docname", "owner", "creation", "modified"]


def _validated_content(content):
	if not isinstance(content, str):
		frappe.throw(_("Note content must be text."), frappe.ValidationError)

	content = content.strip()
	if not content:
		frappe.throw(_("Note content cannot be empty."), frappe.ValidationError)
	if len(content) > 20000:
		frappe.throw(_("Note content cannot exceed 20,000 characters."), frappe.ValidationError)
	return content


def _resolve_reference(reference_doctype, reference_docname, permission_type):
	if reference_doctype not in ALLOWED_REFERENCE_DOCTYPES:
		frappe.throw(_("Notes are only supported for CRM Lead and CRM Student."), frappe.ValidationError)
	lead_name = resolve_lead_name(reference_docname) if reference_doctype == "CRM Lead" else reference_docname
	canonical_name = canonical_student(lead_name)
	resolved_name = canonical_name or lead_name
	resolved_doctype = "CRM Student" if canonical_name else reference_doctype
	reference_doc = frappe.get_doc(resolved_doctype, resolved_name)
	reference_doc.check_permission(permission_type)
	return resolved_name, reference_doc


def _check_reference_access(reference_doctype, reference_docname, permission_type):
	return _resolve_reference(reference_doctype, reference_docname, permission_type)[1]


def _with_owner_full_name(note):
	as_dict = getattr(note, "as_dict", None)
	data = as_dict() if callable(as_dict) else dict(note)
	data["owner_full_name"] = (
		frappe.get_cached_value("User", data.get("owner"), "full_name") if data.get("owner") else None
	)
	return data


@frappe.whitelist()
def list_notes(reference_doctype, reference_docname, search=None, start=0, page_length=20):
	"""List FCRM Notes attached to one CRM Lead or CRM Student.

	Requires read access to that student/contact. Optional search matches content.
	"""
	resolved_name, reference_doc = _resolve_reference(reference_doctype, reference_docname, "read")

	# Keep legacy Lead notes addressable while writing all new notes against the
	# canonical Student.name. This is a compatibility boundary, not a second
	# source of truth.
	lead_name = resolve_lead_name(reference_docname) if reference_doctype == "CRM Lead" else reference_docname
	reference_names = list(dict.fromkeys([reference_docname, lead_name, resolved_name]))
	resolved_doctype = reference_doc.doctype
	filters = {"reference_docname": ["in", reference_names]}
	if resolved_doctype == "CRM Student" and reference_doctype == "CRM Lead":
		filters["reference_doctype"] = ["in", ["CRM Lead", "CRM Student"]]
	else:
		filters["reference_doctype"] = resolved_doctype
	if search:
		filters["content"] = ["like", f"%{search}%"]

	result = paged_list(
		"FCRM Note",
		FIELDS,
		filters=filters,
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
	"""Create an FCRM Note on a CRM Lead or CRM Student. Requires read
	access to that student/contact and create access to FCRM Note.
	"""
	resolved_name, reference_doc = _resolve_reference(reference_doctype, reference_docname, "read")
	doc = frappe.new_doc("FCRM Note")
	doc.content = _validated_content(content or "")
	doc.reference_doctype = reference_doc.doctype
	doc.reference_docname = resolved_name
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
		doc.content = _validated_content(content)
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


@frappe.whitelist()
def list_lead_notes(lead_id, search=None, start=0, page_length=20):
	"""List notes attached to one CRM Lead through the Lead detail contract."""
	return list_notes("CRM Lead", lead_id, search=search, start=start, page_length=page_length)


@frappe.whitelist()
def get_lead_note(name):
	"""Get one legacy Lead note or a Student note created via the Lead alias."""
	doc = get_note(name)
	if doc.get("reference_doctype") not in {"CRM Lead", "CRM Student"}:
		frappe.throw(_("Note is not attached to a CRM Lead or CRM Student."), frappe.ValidationError)
	return doc


@frappe.whitelist(methods=["POST"])
def create_lead_note(lead_id, content=None):
	"""Create a note attached to a CRM Lead."""
	return create_note("CRM Lead", lead_id, content=content)


@frappe.whitelist(methods=["POST", "PUT"])
def update_lead_note(name, content=None):
	"""Update a legacy Lead note or a Student note created via the Lead alias."""
	doc = get_note(name)
	if doc.get("reference_doctype") not in {"CRM Lead", "CRM Student"}:
		frappe.throw(_("Note is not attached to a CRM Lead or CRM Student."), frappe.ValidationError)
	return update_note(name, content=content)


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_lead_note(name):
	"""Delete a legacy Lead note or a Student note created via the Lead alias."""
	doc = get_note(name)
	if doc.get("reference_doctype") not in {"CRM Lead", "CRM Student"}:
		frappe.throw(_("Note is not attached to a CRM Lead or CRM Student."), frappe.ValidationError)
	return delete_note(name)
