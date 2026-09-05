"""Task APIs scoped to CRM Student / CRM Contact.

Task DocType permissions grant the supported sales roles the required CRUD
operations, while the permission hooks below add record-level checks on the
referenced Student or Contact. A task can only be read or changed when the
caller can see its parent record.

The aggregate reader also lives here because it is the shared read path for
Sales, CTV Sale and Lead Sales task workbenches.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.db_query import DatabaseQuery
from frappe.utils import get_datetime, now_datetime

from crm.api._pagination import paged_list
from crm.fcrm.role_policy import resolve_compatibility_overlay, resolve_crm_profile

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

_MAX_AGGREGATE_PAGE_LENGTH = 100
_AGGREGATE_DATE_FILTERS = {"all", "today", "overdue", "upcoming"}
_AGGREGATE_SORTS = {"due_date_asc", "modified_desc", "created_desc"}
_GENERIC_TASK_STATUSES = ("Backlog", "Todo", "In Progress")
_GENERIC_TERMINAL_STATUSES = ("Done", "Canceled")
_ACTION_OPEN_STATES = ("pending", "accepted", "in-progress", "requires-review", "deferred")
_ACTION_TERMINAL_STATES = ("completed", "cancelled", "rejected", "superseded")
_SALES_TASK_PROFILES = {"sales", "ctv_sale", "lead_sales"}
_SALES_TASK_OVERLAYS = {"sales_own", "team_leader"}


def _is_sales_task_actor(actor):
	roles = set(frappe.get_roles(actor))
	profile = resolve_crm_profile(roles)
	overlay = resolve_compatibility_overlay(roles)
	return profile in _SALES_TASK_PROFILES or overlay in _SALES_TASK_OVERLAYS


def _require_sales_task_access():
	"""Authorize the aggregate reader and apply Student/Contact row scope."""
	actor = frappe.session.user
	if actor == "Guest":
		frappe.throw(_("Authentication is required."), frappe.PermissionError)

	if actor == "Administrator" or "System Manager" in frappe.get_roles(actor):
		return actor

	if not _is_sales_task_actor(actor):
		frappe.throw(_("Sale, CTV Sale or Lead Sales access is required."), frappe.PermissionError)
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
		f"CASE WHEN {task_table}.reference_doctype = 'CRM Student' "
		f"THEN NULLIF({task_table}.reference_docname, '') END)"
	)
	contact_reference = (
		f"CASE WHEN {task_table}.reference_doctype = 'CRM Contact' "
		f"THEN NULLIF({task_table}.reference_docname, '') END"
	)
	return f"""(
		EXISTS (
			SELECT 1 FROM `tabCRM Student` student_scope
			WHERE student_scope.name = {student_reference}
			AND ({student_condition})
		)
		OR EXISTS (
			SELECT 1 FROM `tabCRM Contact` contact_scope
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

	student_condition = _permission_condition("CRM Student", "student_scope", actor)
	contact_condition = _permission_condition("CRM Contact", "contact_scope", actor)
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


def _student_expression(table_alias):
	return (
		f"COALESCE(NULLIF({table_alias}.student, ''), "
		f"CASE WHEN {table_alias}.reference_doctype = 'CRM Student' "
		f"THEN NULLIF({table_alias}.reference_docname, '') END, "
		f"NULLIF(contact.student, ''))"
	)


def _contact_expression(table_alias):
	return (
		f"CASE WHEN {table_alias}.reference_doctype = 'CRM Contact' "
		f"THEN NULLIF({table_alias}.reference_docname, '') END"
	)


def _generic_scope_condition(student_condition, contact_condition):
	student_expression = _student_expression("task")
	contact_expression = _contact_expression("task")
	return f"""(
		EXISTS (
			SELECT 1 FROM `tabCRM Student` student_scope
			WHERE student_scope.name = {student_expression}
			AND ({student_condition})
		)
		OR EXISTS (
			SELECT 1 FROM `tabCRM Contact` contact_scope
			WHERE contact_scope.name = {contact_expression}
			AND ({contact_condition})
		)
	)"""


def _action_scope_condition(student_condition):
	return f"""EXISTS (
		SELECT 1 FROM `tabCRM Student` student_scope
		WHERE student_scope.name = action_item.student
		AND ({student_condition})
	)"""


def _status_condition(status, *, source):
	if not status:
		return "1=1"
	field = "task.status" if source == "generic" else "action_item.state"
	if status.lower() == "open":
		values = _GENERIC_TASK_STATUSES if source == "generic" else _ACTION_OPEN_STATES
		return f"{field} IN ({', '.join('%s' for _ in values)})"
	if status.lower() in {"completed", "done"}:
		return "task.status = %s" if source == "generic" else "action_item.state = %s"
	if status.lower() in {"cancelled", "canceled"}:
		return "task.status = %s" if source == "generic" else "action_item.state = %s"
	return f"LOWER({field}) = LOWER(%s)"


def _status_values(status, *, source):
	if not status:
		return []
	if status.lower() == "open":
		return list(_GENERIC_TASK_STATUSES if source == "generic" else _ACTION_OPEN_STATES)
	if status.lower() in {"completed", "done"}:
		return ["Done" if source == "generic" else "completed"]
	if status.lower() in {"cancelled", "canceled"}:
		return ["Canceled" if source == "generic" else "cancelled"]
	return [status]


def _date_condition(date_filter, due_field, status_field, *, source):
	if date_filter == "all":
		return "1=1"
	if date_filter == "today":
		return f"DATE({due_field}) = %s"
	if date_filter == "upcoming":
		return f"{due_field} >= %s"
	terminal = _GENERIC_TERMINAL_STATUSES if source == "generic" else _ACTION_TERMINAL_STATES
	return f"{due_field} < %s AND {status_field} NOT IN ({', '.join('%s' for _ in terminal)})"


def _search_condition(search, *, source):
	if not search:
		return "1=1"
	if source == "generic":
		fields = (
			"task.title",
			"task.description",
			"student.student_name",
			"contact.full_name",
			"task.assigned_to",
			"assigned_user.full_name",
		)
	else:
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


def _filter_values(search, status, priority, date_filter, *, source):
	values = []
	if search:
		values.extend([f"%{search}%"] * (6 if source == "generic" else 7))
	values.extend(_status_values(status, source=source))
	if priority:
		values.append(priority)
	if date_filter == "today":
		values.append(frappe.utils.today())
	elif date_filter in {"upcoming", "overdue"}:
		values.append(now_datetime())
	if date_filter == "overdue":
		values.extend(_GENERIC_TERMINAL_STATUSES if source == "generic" else _ACTION_TERMINAL_STATES)
	return values


def _generic_task_query(
	student_condition, contact_condition, search, status, priority, date_filter, task_type
):
	student_expression = _student_expression("task")
	contact_expression = _contact_expression("task")
	conditions = [
		"NOT EXISTS (SELECT 1 FROM `tabCRM Action Item` migrated WHERE migrated.legacy_generic_task = task.name)",
		_generic_scope_condition(student_condition, contact_condition),
		_search_condition(search, source="generic"),
		_status_condition(status, source="generic"),
	]
	if priority:
		conditions.append("LOWER(task.priority) = LOWER(%s)")
	conditions.append(_date_condition(date_filter, "task.due_date", "task.status", source="generic"))
	if task_type and task_type.lower() not in {"task", "generic", "manual", "legacy"}:
		return None, []
	query = f"""
		SELECT
			CONCAT('Task:', task.name) AS task_id,
			task.name AS name,
			'Task' AS doctype,
			'Task' AS task_type,
			task.title AS title,
			task.description AS description,
			task.status AS status,
			task.priority AS priority,
			task.due_date AS due_date,
			task.assigned_to AS assigned_to,
			assigned_user.full_name AS assigned_to_name,
			{student_expression} AS student,
			COALESCE(student.student_name, contact.full_name) AS student_name,
			task.reference_doctype AS reference_doctype,
			task.reference_docname AS reference_docname,
			task.linked_interaction AS linked_interaction,
			NULL AS action,
			NULL AS action_type,
			NULL AS origin,
			task.creation AS created_at,
			task.modified AS modified
		FROM `tabTask` task
		LEFT JOIN `tabCRM Contact` contact ON contact.name = {contact_expression}
		LEFT JOIN `tabCRM Student` student ON student.name = {student_expression}
		LEFT JOIN `tabUser` assigned_user ON assigned_user.name = task.assigned_to
		WHERE {" AND ".join(conditions)}
	"""
	return query, _filter_values(search, status, priority, date_filter, source="generic")


def _action_query(student_condition, search, status, priority, date_filter, task_type):
	conditions = [
		_action_scope_condition(student_condition),
		_search_condition(search, source="action"),
		_status_condition(status, source="action"),
	]
	if priority:
		conditions.append("LOWER(action_item.priority) = LOWER(%s)")
	conditions.append(
		_date_condition(date_filter, "action_item.due_at", "action_item.state", source="action")
	)
	if task_type and task_type.lower() in {"task", "generic", "manual", "legacy"}:
		return None, []
	if task_type:
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
			action_item.objective AS description,
			action_item.state AS status,
			action_item.priority AS priority,
			action_item.due_at AS due_date,
			action_item.action_owner AS assigned_to,
			assigned_staff.full_name AS assigned_to_name,
			action_item.student AS student,
			COALESCE(student.student_name, contact.full_name) AS student_name,
			CASE WHEN action_item.student IS NOT NULL AND action_item.student != '' THEN 'CRM Student' ELSE 'CRM Contact' END AS reference_doctype,
			COALESCE(NULLIF(action_item.student, ''), NULLIF(action_item.contact, '')) AS reference_docname,
			action_item.linked_interaction AS linked_interaction,
			action_item.action AS action,
			action_item.action_type AS action_type,
			action_item.origin AS origin,
			action_item.created_at AS created_at,
			action_item.modified AS modified
		FROM `tabCRM Action Item` action_item
		LEFT JOIN `tabCRM Student` student ON student.name = action_item.student
		LEFT JOIN `tabCRM Contact` contact ON contact.name = action_item.contact
		LEFT JOIN `tabCRM Staff` assigned_staff ON assigned_staff.name = action_item.action_owner
		WHERE {" AND ".join(conditions)}
	"""
	values = _filter_values(search, status, priority, date_filter, source="action")
	if task_type:
		values.append(task_type)
	return query, values


def _aggregate_tasks_sql(actor, search, status, priority, date_filter, task_type):
	student_condition = _permission_condition("CRM Student", "student_scope", actor)
	contact_condition = _permission_condition("CRM Contact", "contact_scope", actor)
	queries = []
	values = []

	generic_query, generic_values = _generic_task_query(
		student_condition, contact_condition, search, status, priority, date_filter, task_type
	)
	if generic_query:
		queries.append(generic_query)
		values.extend(generic_values)

	action_query, action_values = _action_query(
		student_condition, search, status, priority, date_filter, task_type
	)
	if action_query:
		queries.append(action_query)
		values.extend(action_values)

	return " UNION ALL ".join(queries), values


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
	terminal = (
		status in _GENERIC_TERMINAL_STATUSES
		if row.get("doctype") == "Task"
		else status in _ACTION_TERMINAL_STATES
	)
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
	"""Return one permission-scoped, aggregate task page for Sales profiles.

	The response deliberately normalizes legacy ``Task`` and canonical
	``CRM Action Item`` rows into one collection. Legacy admissions Tasks that
	have already been migrated are excluded by ``legacy_generic_task`` so the
	client never sees a duplicate task.
	"""
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
