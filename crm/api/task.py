"""CRUD API for Tasks scoped to CRM Student / CRM Contact.

Task keeps global DocType permissions for the Desk, while these entry points
add the record-level check on the referenced Student or Contact. A task can
only be read or changed through this API when the caller can see its parent
record.
"""

import frappe
from frappe import _

from crm.api._pagination import paged_list

ALLOWED_REFERENCE_DOCTYPES = {"CRM Student", "CRM Contact"}

FIELDS = [
	"name",
	"title",
	"description",
	"student",
	"linked_interaction",
	"priority",
	"start_date",
	"assigned_to",
	"status",
	"due_date",
	"reference_doctype",
	"reference_docname",
	"owner",
	"creation",
	"modified",
]


def _check_reference_access(reference_doctype, reference_docname, permission_type):
	if reference_doctype not in ALLOWED_REFERENCE_DOCTYPES:
		frappe.throw(_("Tasks are only supported for CRM Student and CRM Contact."), frappe.ValidationError)
	reference_doc = frappe.get_doc(reference_doctype, reference_docname)
	reference_doc.check_permission(permission_type)
	return reference_doc


@frappe.whitelist()
def list_tasks(reference_doctype, reference_docname, search=None, status=None, start=0, page_length=20):
	"""List Tasks attached to one CRM Student or CRM Contact."""
	_check_reference_access(reference_doctype, reference_docname, "read")

	filters = {"reference_doctype": reference_doctype, "reference_docname": reference_docname}
	if status:
		filters["status"] = status

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [["title", "like", like], ["description", "like", like]]

	result = paged_list(
		"Task",
		FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="modified desc",
	)
	rows = result.pop("rows")
	return {**result, "tasks": rows}


@frappe.whitelist()
def get_task(name):
	"""Get one Task and require read access to its referenced record."""
	doc = frappe.get_doc("Task", name)
	doc.check_permission("read")
	_check_reference_access(doc.reference_doctype, doc.reference_docname, "read")
	return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def create_task(
	reference_doctype,
	reference_docname,
	title,
	description=None,
	priority=None,
	start_date=None,
	assigned_to=None,
	status=None,
	due_date=None,
	linked_interaction=None,
):
	"""Create a Task attached to a CRM Student or CRM Contact."""
	_check_reference_access(reference_doctype, reference_docname, "read")

	doc = frappe.new_doc("Task")
	doc.title = title
	doc.description = description
	doc.priority = priority
	doc.start_date = start_date
	doc.assigned_to = assigned_to
	doc.status = status
	doc.due_date = due_date
	doc.linked_interaction = linked_interaction
	doc.reference_doctype = reference_doctype
	doc.reference_docname = reference_docname
	if reference_doctype == "CRM Student":
		doc.student = reference_docname
	doc.insert()
	return doc.as_dict()


@frappe.whitelist(methods=["POST", "PUT"])
def update_task(
	name,
	title=None,
	description=None,
	priority=None,
	start_date=None,
	assigned_to=None,
	status=None,
	due_date=None,
	linked_interaction=None,
):
	"""Update mutable Task fields without moving its referenced record."""
	doc = frappe.get_doc("Task", name)
	doc.check_permission("write")
	_check_reference_access(doc.reference_doctype, doc.reference_docname, "read")

	values = {
		"title": title,
		"description": description,
		"priority": priority,
		"start_date": start_date,
		"assigned_to": assigned_to,
		"status": status,
		"due_date": due_date,
		"linked_interaction": linked_interaction,
	}
	for fieldname, value in values.items():
		if value is not None:
			setattr(doc, fieldname, value)

	doc.save()
	return doc.as_dict()


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_task(name):
	"""Delete a Task after checking access to its referenced record."""
	doc = frappe.get_doc("Task", name)
	doc.check_permission("delete")
	_check_reference_access(doc.reference_doctype, doc.reference_docname, "read")
	doc.delete()
	return {"deleted": name}
