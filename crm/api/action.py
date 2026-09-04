import frappe
from frappe import _

from crm.api._pagination import paged_list
from crm.fcrm.nba_timing import TIME_SLOTS

FIELDS = [
	"name",
	"code",
	"display_name",
	"action_type",
	"description",
	"purpose",
	"default_channel",
	"allowed_actors",
	"allowed_time_slots",
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
	"allowed_time_slots",
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
def list_time_slots():
	"""List the daily time-slot codes usable in CRM Action.allowed_time_slots."""
	return {"time_slots": list(TIME_SLOTS)}


@frappe.whitelist()
def list_actions(action_type=None, enabled=None, search=None, start=0, page_length=20):
	"""List CRM Action catalog rows.

	Filter by action_type (Link -> CRM Action Type), enabled (0/1), or search
	(matches code/display_name/purpose). Paginated with start/page_length.
	"""
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
	"""Get one CRM Action by name (its "name" is the same as "code")."""
	doc = frappe.get_doc("CRM Action", name)
	doc.check_permission("read")
	return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def create_action(**values):
	"""Create a CRM Action. code/action_type must be one of the canonical 79
	action-catalog entries (crm.fcrm.action_type_catalog); System Manager only.
	"""
	doc = frappe.new_doc("CRM Action")
	_set_writable_fields(doc, values)
	doc.insert()
	return doc.as_dict()


@frappe.whitelist(methods=["POST", "PUT"])
def update_action(name, **values):
	"""Update a CRM Action. code is immutable once created; System Manager only."""
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
	"""Delete a CRM Action by name; System Manager only."""
	doc = frappe.get_doc("CRM Action", name)
	doc.check_permission("delete")
	doc.delete()
	return {"deleted": name}
