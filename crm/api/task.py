"""Task APIs scoped to CRM Lead / CRM Student.

Task DocType permissions grant the supported sales roles the required CRUD
operations, while the permission hooks below add record-level checks on the
referenced Student or Contact. A task can only be read or changed when the
caller can see its parent record.

The aggregate reader also lives here because it is the shared read path for
Sales, CTV Sale and Lead Sale task workbenches.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.db_query import DatabaseQuery
from frappe.utils import get_datetime, now_datetime

from crm.api._pagination import paged_list
from crm.fcrm.role_policy import resolve_crm_profile
from crm.fcrm.student_decision import (
	create_manual_action,
	delete_manual_action,
	update_manual_action,
)

ALLOWED_REFERENCE_DOCTYPES = {"CRM Lead", "CRM Student"}

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

_MAX_AGGREGATE_PAGE_LENGTH = 100
_AGGREGATE_DATE_FILTERS = {"all", "today", "overdue", "upcoming"}
_AGGREGATE_SORTS = {"due_date_asc", "modified_desc", "created_desc"}
_ACTION_OPEN_STATES = ("pending", "accepted", "in-progress", "requires-review", "deferred")
_ACTION_TERMINAL_STATES = ("completed", "cancelled", "rejected", "superseded")
_SALES_TASK_PROFILES = {"sales", "ctv_sale", "lead_sales"}
_TASK_STATUS_TO_ACTION_STATE = {
	"backlog": "pending",
	"pending": "pending",
	"todo": "accepted",
	"accepted": "accepted",
	"in progress": "in-progress",
	"in-progress": "in-progress",
	"in_progress": "in-progress",
	"requires-review": "requires-review",
	"done": "completed",
	"completed": "completed",
	"canceled": "cancelled",
	"cancelled": "cancelled",
}
_ACTION_STATE_TO_TASK_STATUS = {
	"pending": "Backlog",
	"accepted": "Todo",
	"in-progress": "In Progress",
	"requires-review": "In Progress",
	"deferred": "Backlog",
	"completed": "Done",
	"cancelled": "Canceled",
	"rejected": "Canceled",
	"superseded": "Canceled",
}
_ACTION_ITEM_FIELDS = [
	"name",
	"student",
	"contact",
	"objective",
	"description",
	"start_date",
	"linked_interaction",
	"priority",
	"due_at",
	"action_owner",
	"action",
	"action_type",
	"state",
	"legacy_task_deleted",
	"owner",
	"creation",
	"modified",
]


def _is_sales_task_actor(actor):
	roles = set(frappe.get_roles(actor))
	profile = resolve_crm_profile(roles)
	return profile in _SALES_TASK_PROFILES


def _require_sales_task_access():
	"""Authorize the aggregate reader and apply Student/Contact row scope."""
	actor = frappe.session.user
	if actor == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)

	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return actor

	if not _is_sales_task_actor(actor):
		frappe.throw(_("Sale, CTV Sale or Lead Sale access is required."), frappe.PermissionError)
	return actor


def _parse_aggregate_page(value, field, default, maximum):
	try:
		parsed = int(value)
	except (TypeError, ValueError):
		frappe.throw(_("{0} must be an integer.").format(field), frappe.ValidationError)
	if parsed < 0 or (field == "page_length" and not 1 <= parsed <= maximum):
		message = (
			_("page_length must be between 1 and {0}.").format(maximum)
			if field == "page_length"
			else _("start must be zero or greater.")
		)
		frappe.throw(message, frappe.ValidationError)
	if field == "page_length":
		return parsed or default
	return parsed


def _normalize_aggregate_filters(date_filter, status, priority, task_type, sort_by):
	date_filter = str(date_filter or "all").strip().lower()
	if date_filter not in _AGGREGATE_DATE_FILTERS:
		frappe.throw(
			_("date_filter must be one of all, today, overdue, or upcoming."), frappe.ValidationError
		)

	sort_by = str(sort_by or "due_date_asc").strip().lower()
	if sort_by not in _AGGREGATE_SORTS:
		frappe.throw(_("sort_by is not supported."), frappe.ValidationError)

	def _optional(value):
		value = str(value or "").strip()
		return value if value and value.lower() != "all" else None

	return date_filter, _optional(status), _optional(priority), _optional(task_type), sort_by


def _permission_condition(doctype, alias, actor):
	"""Return Frappe's row condition rebound to a SQL subquery alias."""
	condition = DatabaseQuery(doctype, user=actor).build_match_conditions(as_condition=True)
	if not condition:
		return "1=1"
	return condition.replace(f"`tab{doctype}`", alias)


def _task_reference_scope_condition(student_condition, contact_condition):
	"""Scope generic Task queries through their CRM Student or Contact reference."""
	task_table = "`tabTask`"
	student_reference = (
		f"COALESCE(NULLIF({task_table}.student, ''), "
		f"CASE WHEN {task_table}.reference_doctype = 'CRM Lead' "
		f"THEN NULLIF({task_table}.reference_docname, '') END)"
	)
	contact_reference = (
		f"CASE WHEN {task_table}.reference_doctype = 'CRM Student' "
		f"THEN NULLIF({task_table}.reference_docname, '') END"
	)
	return f"""(
		EXISTS (
			SELECT 1 FROM `tabCRM Lead` student_scope
			WHERE student_scope.name = {student_reference}
			AND ({student_condition})
		)
		OR EXISTS (
			SELECT 1 FROM `tabCRM Student` contact_scope
			WHERE contact_scope.name = {contact_reference}
			AND ({contact_condition})
		)
	)"""


def get_permission_query_conditions(user=None):
	"""Limit Desk/REST Task lists to CRM records visible to the current user."""
	actor = user or frappe.session.user
	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return None
	if not _is_sales_task_actor(actor):
		return None

	student_condition = _permission_condition("CRM Lead", "student_scope", actor)
	contact_condition = _permission_condition("CRM Student", "contact_scope", actor)
	if student_condition == "1=0" and contact_condition == "1=0":
		return "1=0"
	return _task_reference_scope_condition(student_condition, contact_condition)


def _has_task_reference_permission(doc):
	"""Return whether the caller can read the Task's referenced CRM record."""
	reference_doctype = doc.get("reference_doctype")
	reference_docname = doc.get("reference_docname")
	if not reference_doctype or not reference_docname:
		return False
	try:
		_check_reference_access(reference_doctype, reference_docname, "read")
	except (frappe.DoesNotExistError, frappe.PermissionError, frappe.ValidationError):
		return False
	return True


def has_permission(doc, user=None, permission_type=None, ptype=None):
	"""Apply the same reference scope to direct Task reads and writes."""
	if not doc:
		return None
	actor = user or frappe.session.user
	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return None
	if not _is_sales_task_actor(actor):
		return None
	return _has_task_reference_permission(doc)


def _action_scope_condition(student_condition):
	return f"""EXISTS (
		SELECT 1 FROM `tabCRM Lead` student_scope
		WHERE student_scope.name = action_item.student
		AND ({student_condition})
	)"""


def _status_condition(status):
	if not status:
		return "1=1"
	field = "action_item.state"
	if status.lower() == "open":
		return f"{field} IN ({', '.join('%s' for _ in _ACTION_OPEN_STATES)})"
	if status.lower() in {"completed", "done"}:
		return "action_item.state = %s"
	if status.lower() in {"cancelled", "canceled"}:
		return "action_item.state = %s"
	return f"LOWER({field}) = LOWER(%s)"


def _status_values(status):
	if not status:
		return []
	if status.lower() == "open":
		return list(_ACTION_OPEN_STATES)
	if status.lower() in {"completed", "done"}:
		return ["completed"]
	if status.lower() in {"cancelled", "canceled"}:
		return ["cancelled"]
	return [status]


def _date_condition(date_filter, due_field, status_field):
	if date_filter == "all":
		return "1=1"
	if date_filter == "today":
		return f"DATE({due_field}) = %s"
	if date_filter == "upcoming":
		return f"{due_field} >= %s"
	return f"{due_field} < %s AND {status_field} NOT IN ({', '.join('%s' for _ in _ACTION_TERMINAL_STATES)})"


def _search_condition(search):
	if not search:
		return "1=1"
	fields = (
		"action_item.objective",
		"action_item.action",
		"action_item.action_type",
		"student.student_name",
		"contact.full_name",
		"action_item.action_owner",
		"assigned_staff.full_name",
	)
	return "(" + " OR ".join(f"{field} LIKE %s" for field in fields) + ")"


def _filter_values(search, status, priority, date_filter):
	values = []
	if search:
		values.extend([f"%{search}%"] * 7)
	values.extend(_status_values(status))
	if priority:
		values.append(priority)
	if date_filter == "today":
		values.append(frappe.utils.today())
	elif date_filter in {"upcoming", "overdue"}:
		values.append(now_datetime())
	if date_filter == "overdue":
		values.extend(_ACTION_TERMINAL_STATES)
	return values


def _action_query(student_condition, search, status, priority, date_filter, task_type):
	conditions = [
		"action_item.legacy_task_deleted = 0",
		_action_scope_condition(student_condition),
		_search_condition(search),
		_status_condition(status),
	]
	if priority:
		conditions.append("LOWER(action_item.priority) = LOWER(%s)")
	conditions.append(_date_condition(date_filter, "action_item.due_at", "action_item.state"))
	if task_type and task_type.lower() in {"task", "generic", "manual", "legacy"}:
		conditions.append("action_item.origin = 'manual'")
		conditions.append("action_item.action = 'CREATE_TASK'")
	elif task_type:
		conditions.append(
			"LOWER(COALESCE(NULLIF(action_item.action_type, ''), "
			"NULLIF(action_item.action, ''), 'CRM Action Item')) = LOWER(%s)"
		)
	query = f"""
		SELECT
			CONCAT('CRM Action Item:', action_item.name) AS task_id,
			action_item.name AS name,
			'CRM Action Item' AS doctype,
			COALESCE(NULLIF(action_item.action_type, ''), NULLIF(action_item.action, ''), 'CRM Action Item') AS task_type,
			action_item.objective AS title,
			COALESCE(NULLIF(action_item.description, ''), action_item.objective) AS description,
			action_item.state AS status,
			action_item.priority AS priority,
			action_item.due_at AS due_date,
			action_item.action_owner AS assigned_to,
			assigned_staff.full_name AS assigned_to_name,
			action_item.student AS student,
			COALESCE(student.student_name, contact.full_name) AS student_name,
			CASE WHEN action_item.student IS NOT NULL AND action_item.student != '' THEN 'CRM Lead' ELSE 'CRM Student' END AS reference_doctype,
			COALESCE(NULLIF(action_item.student, ''), NULLIF(action_item.contact, '')) AS reference_docname,
			action_item.linked_interaction AS linked_interaction,
			action_item.action AS action,
			action_item.action_type AS action_type,
			action_item.origin AS origin,
			action_item.created_at AS created_at,
			action_item.modified AS modified
		FROM `tabCRM Action Item` action_item
		LEFT JOIN `tabCRM Lead` student ON student.name = action_item.student
		LEFT JOIN `tabCRM Student` contact ON contact.name = action_item.contact
		LEFT JOIN `tabCRM Staff` assigned_staff ON assigned_staff.name = action_item.action_owner
		WHERE {" AND ".join(conditions)}
	"""
	values = _filter_values(search, status, priority, date_filter)
	if task_type and task_type.lower() not in {"task", "generic", "manual", "legacy"}:
		values.append(task_type)
	return query, values


def _aggregate_tasks_sql(actor, search, status, priority, date_filter, task_type):
	student_condition = _permission_condition("CRM Lead", "student_scope", actor)
	action_query, action_values = _action_query(
		student_condition, search, status, priority, date_filter, task_type
	)
	return action_query or "", action_values


def _aggregate_order_by(sort_by):
	if sort_by == "modified_desc":
		return "modified DESC, task_id DESC"
	if sort_by == "created_desc":
		return "created_at DESC, task_id DESC"
	return "CASE WHEN due_date IS NULL THEN 1 ELSE 0 END ASC, due_date ASC, modified DESC, task_id ASC"


def _serialize_aggregate_task(row):
	row = dict(row)
	for field in ("due_date", "created_at", "modified"):
		if row.get(field):
			row[field] = str(row[field])

	due_date = get_datetime(row.get("due_date")) if row.get("due_date") else None
	now = now_datetime()
	status = str(row.get("status") or "")
	terminal = status in _ACTION_TERMINAL_STATES
	row["is_today"] = bool(due_date and due_date.date() == now.date())
	row["is_overdue"] = bool(due_date and due_date < now and not terminal)
	return row


@frappe.whitelist()
def list_sales_tasks(
	search=None,
	date_filter="all",
	status=None,
	priority=None,
	task_type=None,
	start=0,
	page_length=20,
	sort_by="due_date_asc",
):
	"""Return one permission-scoped CRM Action Item page for Sales profiles."""
	actor = _require_sales_task_access()
	start = _parse_aggregate_page(start, "start", 0, _MAX_AGGREGATE_PAGE_LENGTH)
	page_length = _parse_aggregate_page(page_length, "page_length", 20, _MAX_AGGREGATE_PAGE_LENGTH)
	date_filter, status, priority, task_type, sort_by = _normalize_aggregate_filters(
		date_filter, status, priority, task_type, sort_by
	)
	if search is not None:
		search = str(search).strip()
		if len(search) > 140:
			frappe.throw(_("search must be 140 characters or fewer."), frappe.ValidationError)

	union_query, filter_values = _aggregate_tasks_sql(actor, search, status, priority, date_filter, task_type)
	if not union_query:
		return {
			"tasks": [],
			"total": 0,
			"total_count": 0,
			"start": start,
			"page_length": page_length,
			"has_more": False,
		}

	count = frappe.db.sql(
		f"SELECT COUNT(*) AS total FROM ({union_query}) aggregate_tasks",
		filter_values,
		as_dict=True,
	)
	total = int(count[0].get("total", 0)) if count else 0
	rows = frappe.db.sql(
		f"""SELECT * FROM ({union_query}) aggregate_tasks
			ORDER BY {_aggregate_order_by(sort_by)}
			LIMIT %s OFFSET %s""",
		[*(filter_values or []), page_length, start],
		as_dict=True,
	)
	tasks = [_serialize_aggregate_task(row) for row in rows]
	return {
		"tasks": tasks,
		"total": total,
		"total_count": total,
		"start": start,
		"page_length": page_length,
		"has_more": start + len(tasks) < total,
	}


def _check_reference_access(reference_doctype, reference_docname, permission_type):
	if reference_doctype not in ALLOWED_REFERENCE_DOCTYPES:
		frappe.throw(_("Tasks are only supported for CRM Student and CRM Student."), frappe.ValidationError)
	reference_doc = frappe.get_doc(reference_doctype, reference_docname)
	reference_doc.check_permission(permission_type)
	return reference_doc


def _task_status_to_action_state(status, *, default=None):
	if status in (None, ""):
		return default
	key = str(status).strip().lower()
	try:
		return _TASK_STATUS_TO_ACTION_STATE[key]
	except KeyError:
		frappe.throw(_("Unsupported Task status."), frappe.ValidationError)


def _priority_to_action(priority, *, default="medium"):
	if priority in (None, ""):
		return default
	value = str(priority).strip().lower()
	if value not in {"low", "medium", "high"}:
		frappe.throw(_("Unsupported Task priority."), frappe.ValidationError)
	return value


def _priority_to_task(priority):
	return str(priority).capitalize() if priority else priority


def _action_reference(action):
	"""Return the old Task reference pair for an Action Item."""
	if action.get("student"):
		return "CRM Lead", action.student
	if action.get("contact"):
		return "CRM Student", action.contact
	return "CRM Lead", action.student


def _action_scope_reference(action):
	"""Return the canonical permission scope for an Action Item."""
	return "CRM Lead", action.get("student")


def _action_item_to_task(action, *, reference_doctype=None, reference_docname=None):
	"""Adapt a canonical Action Item to the unchanged Task response DTO."""
	if not isinstance(action, dict):
		action = action.as_dict()
	if not reference_doctype or not reference_docname:
		reference_doctype, reference_docname = _action_reference(action)
	assigned_to = None
	if action.get("action_owner"):
		assigned_to = frappe.db.get_value("CRM Staff", action.action_owner, "user")
	return {
		"name": action.get("name"),
		"title": action.get("objective"),
		"description": action.get("description") or action.get("objective"),
		"action_code": action.get("action") or action.get("action_type"),
		"student": action.get("student"),
		"linked_interaction": action.get("linked_interaction"),
		"priority": _priority_to_task(action.get("priority")),
		"start_date": action.get("start_date"),
		"assigned_to": assigned_to,
		"status": _ACTION_STATE_TO_TASK_STATUS.get(action.get("state"), action.get("state")),
		"due_date": action.get("due_at"),
		"reference_doctype": reference_doctype,
		"reference_docname": reference_docname,
		"owner": action.get("owner"),
		"creation": action.get("creation") or action.get("created_at"),
		"modified": action.get("modified"),
	}


def _action_item_for_task(name):
	if not frappe.db.exists("CRM Action Item", name):
		return None
	action = frappe.get_doc("CRM Action Item", name)
	if action.get("legacy_task_deleted"):
		frappe.throw(_("This Task has been deleted."), frappe.DoesNotExistError)
	return action


def _assigned_staff_for_user(user):
	if user in (None, ""):
		return None
	if isinstance(user, dict):
		values = [user.get(field) for field in ("name", "email", "user", "value", "full_name")]
	else:
		values = [user]
	values = list(dict.fromkeys(str(value).strip() for value in values if value not in (None, "")))
	if not values:
		return None
	# The legacy Task contract exposes a User value, while some callers use the
	# CRM Staff link value or its display label. Resolve all three to the
	# canonical CRM Staff name before passing it to the Action command service.
	for value in values:
		staff = frappe.db.get_value("CRM Staff", value, "name")
		if not staff:
			staff = frappe.db.get_value("CRM Staff", {"user": value}, "name")
		if not staff:
			staff = frappe.db.get_value("CRM Staff", {"full_name": value}, "name")
		if staff:
			return staff

	# Some User Link controls submit the User's display name. Resolve that
	# display value back to a User first, then use the CRM Staff relation.
	for value in values:
		user_name = frappe.db.get_value("User", value, "name")
		if not user_name:
			user_name = frappe.db.get_value("User", {"email": value}, "name")
		if not user_name:
			user_name = frappe.db.get_value("User", {"full_name": value, "enabled": 1}, "name")
		if user_name:
			staff = frappe.db.get_value("CRM Staff", {"user": user_name}, "name")
			if staff:
				return staff

	assigned_value = ", ".join(values)[:140]
	frappe.throw(
		_("assigned_to '{0}' must reference an active CRM Staff/User.").format(assigned_value),
		frappe.ValidationError,
	)


def _action_target(reference_doctype, reference_docname):
	reference_doc = _check_reference_access(reference_doctype, reference_docname, "read")
	if reference_doctype == "CRM Lead":
		return reference_docname, None
	student = reference_doc.get("student")
	return (student, reference_docname) if student else (None, None)


def _compatibility_key(operation, name=None):
	suffix = name or frappe.generate_hash(length=20)
	return f"task-api-{operation}-{suffix}-{frappe.generate_hash(length=12)}"


def _list_action_items(
	search,
	status,
	start,
	page_length,
	*,
	student=None,
	contact=None,
	reference_doctype=None,
	reference_docname=None,
):
	filters = {"legacy_task_deleted": 0}
	if student:
		filters["student"] = student
	if contact:
		filters["contact"] = contact
	if status:
		filters["state"] = _task_status_to_action_state(status)
	or_filters = None
	if search:
		like = f"%{search}%"
		or_filters = [["objective", "like", like], ["description", "like", like]]
	result = paged_list(
		"CRM Action Item",
		_ACTION_ITEM_FIELDS,
		filters=filters,
		or_filters=or_filters,
		start=start,
		page_length=page_length,
		order_by="modified desc",
	)
	rows = result.pop("rows")
	return {
		**result,
		"tasks": [
			_action_item_to_task(
				row,
				reference_doctype=reference_doctype,
				reference_docname=reference_docname,
			)
			for row in rows
		],
	}


def _list_legacy_tasks(reference_doctype, reference_docname, search, status, start, page_length):
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
def list_tasks(
	reference_doctype=None,
	reference_docname=None,
	search=None,
	status=None,
	start=0,
	page_length=20,
):
	"""List Task-shaped rows; Student-backed rows come from CRM Action Item."""
	if bool(reference_doctype) != bool(reference_docname):
		frappe.throw(
			_("reference_doctype and reference_docname must be supplied together."),
			frappe.ValidationError,
		)
	if not reference_doctype and not reference_docname:
		return _list_action_items(search, status, start, page_length)

	student, contact = _action_target(reference_doctype, reference_docname)
	if not student:
		return _list_legacy_tasks(reference_doctype, reference_docname, search, status, start, page_length)
	return _list_action_items(
		search,
		status,
		start,
		page_length,
		student=student,
		contact=contact,
		reference_doctype=reference_doctype,
		reference_docname=reference_docname,
	)


@frappe.whitelist()
def get_task(name):
	"""Get one Task-shaped row from Task or CRM Action Item."""
	action = _action_item_for_task(name)
	if action:
		scope_doctype, scope_docname = _action_scope_reference(action)
		_check_reference_access(scope_doctype, scope_docname, "read")
		return _action_item_to_task(action)

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
	"""Create a Task-shaped CRM Action Item when the reference has a Student."""
	student, contact = _action_target(reference_doctype, reference_docname)
	if not student:
		# CRM Action Item requires a Student. Keep the old path for standalone
		# Contacts so existing integrations do not lose their legacy records.
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
		doc.insert()
		return doc.as_dict()

	result = create_manual_action(
		student=student,
		contact=contact,
		action_type="CREATE_TASK",
		objective=title,
		description=description,
		start_date=start_date,
		priority=_priority_to_action(priority),
		due_at=due_date,
		linked_interaction=linked_interaction,
		assignee_staff=_assigned_staff_for_user(assigned_to),
		initial_state=_task_status_to_action_state(status, default="pending"),
		idempotency_key=_compatibility_key("create"),
	)
	return _action_item_to_task(
		frappe.get_doc("CRM Action Item", result["action"]),
		reference_doctype=reference_doctype,
		reference_docname=reference_docname,
	)


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
	"""Update a Task-shaped CRM Action Item through its command service."""
	action = _action_item_for_task(name)
	if not action:
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

	scope_doctype, scope_docname = _action_scope_reference(action)
	_check_reference_access(scope_doctype, scope_docname, "read")
	update_manual_action(
		name,
		title=title,
		description=description,
		start_date=start_date,
		priority=_priority_to_action(priority, default=None) if priority is not None else None,
		due_at=due_date,
		assignee_staff=_assigned_staff_for_user(assigned_to) if assigned_to is not None else None,
		action_state=_task_status_to_action_state(status) if status is not None else None,
		linked_interaction=linked_interaction,
		idempotency_key=_compatibility_key("update", name),
	)
	return _action_item_to_task(frappe.get_doc("CRM Action Item", name))


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_task(name):
	"""Delete a Task-shaped row; canonical Action Items are soft-deleted."""
	action = _action_item_for_task(name)
	if action:
		scope_doctype, scope_docname = _action_scope_reference(action)
		_check_reference_access(scope_doctype, scope_docname, "read")
		delete_manual_action(name, idempotency_key=_compatibility_key("delete", name))
		return {"deleted": name}

	doc = frappe.get_doc("Task", name)
	doc.check_permission("delete")
	_check_reference_access(doc.reference_doctype, doc.reference_docname, "read")
	doc.delete()
	return {"deleted": name}
