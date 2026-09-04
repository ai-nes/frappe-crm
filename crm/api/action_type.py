import frappe
from frappe import _

from crm.api._pagination import paged_list

FIELDS = ["name", "action_type", "display_name", "enabled", "sort_order", "modified"]

# "action_type" is the primary key (autoname: field:action_type) and cannot be
# changed after creation, same rule as CRM Action's "code".
WRITABLE_FIELDS = ["action_type", "display_name", "enabled", "sort_order"]


def _set_writable_fields(doc, values):
	for fieldname in WRITABLE_FIELDS:
		if fieldname in values:
			doc.set(fieldname, values[fieldname])


@frappe.whitelist()
def list_action_types(enabled=None, search=None, start=0, page_length=20):
	"""List CRM Action Type categories (the shared groupings behind CRM
	Action.action_type). Filter by enabled (0/1) or search; paginated.
	"""
	filters = {}
	if enabled is not None and enabled != "":
		filters["enabled"] = frappe.utils.cint(enabled)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [["action_type", "like", like], ["display_name", "like", like]]

	result = paged_list(
		"CRM Action Type",
		FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="sort_order asc",
	)
	rows = result.pop("rows")
	return {**result, "action_types": rows}


@frappe.whitelist()
def get_action_type(name):
	"""Get one CRM Action Type by name (its "name" is the category code)."""
	doc = frappe.get_doc("CRM Action Type", name)
	doc.check_permission("read")
	return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def create_action_type(**values):
	"""Create a built-in or custom CRM Action Type category. System Manager only."""
	doc = frappe.new_doc("CRM Action Type")
	_set_writable_fields(doc, values)
	doc.insert()
	return doc.as_dict()


@frappe.whitelist(methods=["POST", "PUT"])
def update_action_type(name, **values):
	"""Update a CRM Action Type. action_type code is immutable once created;
	System Manager only.
	"""
	doc = frappe.get_doc("CRM Action Type", name)
	doc.check_permission("write")
	if "action_type" in values and values["action_type"] != doc.action_type:
		frappe.throw(_("CRM Action Type code cannot be changed after creation."), frappe.ValidationError)
	values.pop("action_type", None)
	_set_writable_fields(doc, values)
	doc.save()
	return doc.as_dict()


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_action_type(name):
	"""Delete a CRM Action Type by name; System Manager only."""
	doc = frappe.get_doc("CRM Action Type", name)
	doc.check_permission("delete")
	doc.delete()
	return {"deleted": name}
