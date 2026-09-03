import frappe
from frappe import _

from crm.api._pagination import paged_list

FIELDS = [
	"name",
	"code",
	"display_name",
	"action_type",
	"description",
	"purpose",
	"default_channel",
	"allowed_actors",
	"requires_approval",
	"auto_execute",
	"execution_type",
	"ai_allowed",
	"enabled",
	"sort_order",
	"modified",
]

# Fields a caller may set through create_action/update_action. "name" is
# derived from "code" via autoname (field:code) and must never be assigned
# directly, and controller validation (crm_action.py) enforces that code/
# action_type stay one of the canonical 79 catalog entries.
WRITABLE_FIELDS = [
	"code",
	"display_name",
	"action_type",
	"description",
	"purpose",
	"default_channel",
	"allowed_actors",
	"requires_approval",
	"auto_execute",
	"execution_type",
	"ai_allowed",
	"enabled",
	"sort_order",
]


def _set_writable_fields(doc, values):
	for fieldname in WRITABLE_FIELDS:
		if fieldname in values:
			doc.set(fieldname, values[fieldname])


@frappe.whitelist()
def list_actions(action_type=None, enabled=None, search=None, start=0, page_length=20):
	filters = {}
	if action_type:
		filters["action_type"] = action_type
	if enabled is not None and enabled != "":
		filters["enabled"] = frappe.utils.cint(enabled)

	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [
			["code", "like", like],
			["display_name", "like", like],
			["purpose", "like", like],
		]

	result = paged_list(
		"CRM Action",
		FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="sort_order asc",
	)
	rows = result.pop("rows")
	return {**result, "actions": rows}


@frappe.whitelist()
def get_action(name):
	doc = frappe.get_doc("CRM Action", name)
	doc.check_permission("read")
	return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def create_action(**values):
	doc = frappe.new_doc("CRM Action")
	_set_writable_fields(doc, values)
	doc.insert()
	return doc.as_dict()


@frappe.whitelist(methods=["POST", "PUT"])
def update_action(name, **values):
	doc = frappe.get_doc("CRM Action", name)
	doc.check_permission("write")
	if "code" in values and values["code"] != doc.code:
		frappe.throw(_("CRM Action code cannot be changed after creation."), frappe.ValidationError)
	values.pop("code", None)
	_set_writable_fields(doc, values)
	doc.save()
	return doc.as_dict()


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_action(name):
	doc = frappe.get_doc("CRM Action", name)
	doc.check_permission("delete")
	doc.delete()
	return {"deleted": name}
