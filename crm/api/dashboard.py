import json

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Count, Date, IfNull

from crm.fcrm.doctype.dashboard.dashboard import create_default_manager_dashboard
from crm.utils import sales_user_only


@frappe.whitelist()
def reset_to_default():
	frappe.only_for("System Manager", True)
	create_default_manager_dashboard(force=True)


@frappe.whitelist()
@sales_user_only
def get_dashboard(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	from_date, to_date, user = normalize_dashboard_filters(from_date, to_date, user)

	dashboard = frappe.db.exists("Dashboard", "Manager Dashboard")
	if not dashboard:
		layout = json.loads(create_default_manager_dashboard())
		frappe.db.commit()
	else:
		layout = json.loads(frappe.db.get_value("Dashboard", "Manager Dashboard", "layout") or "[]")

	for item in layout:
		method = getattr(frappe.get_attr("crm.api.dashboard"), f"get_{item['name']}", None)
		item["data"] = method(from_date, to_date, user) if method else None

	return layout


@frappe.whitelist()
@sales_user_only
def get_chart(
	name: str, type: str, from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	from_date, to_date, user = normalize_dashboard_filters(from_date, to_date, user)

	method = getattr(frappe.get_attr("crm.api.dashboard"), f"get_{name}", None)
	if method:
		return method(from_date, to_date, user)
	return {"error": _("Invalid chart name")}


def normalize_dashboard_filters(from_date=None, to_date=None, user=None):
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	roles = frappe.get_roles(frappe.session.user)
	is_manager = "Sales Manager" in roles or "System Manager" in roles
	is_user = "Sales User" in roles and not is_manager

	if is_user:
		user = frappe.session.user

	return from_date, to_date, user


def get_assigned_crm_staff(user):
	if not user:
		return None
	return frappe.db.get_value("CRM Staff", {"user": user}, "name") or "__none__"


def get_periods(from_date, to_date):
	diff = frappe.utils.date_diff(to_date, from_date) or 1
	prev_from_date = frappe.utils.add_days(from_date, -diff)
	return prev_from_date, frappe.utils.add_days(to_date, 1)


def get_count(doctype, from_date, to_date, user=None, extra_filters=None):
	filters = [
		["creation", ">=", from_date],
		["creation", "<", frappe.utils.add_days(to_date, 1)],
	]

	if doctype == "CRM Contact" and user:
		filters.append(["assigned_to", "=", get_assigned_crm_staff(user)])

	if extra_filters:
		filters.extend(extra_filters)

	return frappe.db.count(doctype, filters=filters)


def get_count_delta(doctype, from_date, to_date, user=None, extra_filters=None):
	prev_from_date, to_date_plus_one = get_periods(from_date, to_date)
	current_filters = [
		["creation", ">=", from_date],
		["creation", "<", to_date_plus_one],
	]
	previous_filters = [
		["creation", ">=", prev_from_date],
		["creation", "<", from_date],
	]

	if doctype == "CRM Contact" and user:
		crm_staff = get_assigned_crm_staff(user)
		current_filters.append(["assigned_to", "=", crm_staff])
		previous_filters.append(["assigned_to", "=", crm_staff])

	if extra_filters:
		current_filters.extend(extra_filters)
		previous_filters.extend(extra_filters)

	current = frappe.db.count(doctype, filters=current_filters)
	previous = frappe.db.count(doctype, filters=previous_filters)
	delta = ((current - previous) / previous * 100) if previous else 0
	return current, delta


def number_chart(title, tooltip, value, delta):
	return {
		"title": _(title),
		"tooltip": _(tooltip),
		"value": value,
		"delta": delta,
		"deltaSuffix": "%",
	}


def get_total_students(from_date=None, to_date=None, user=None):
	value, delta = get_count_delta("CRM Student", from_date, to_date)
	return number_chart("Total students", "Total number of imported enrollment students", value, delta)


def get_total_contacts(from_date=None, to_date=None, user=None):
	value, delta = get_count_delta("CRM Contact", from_date, to_date, user)
	return number_chart("Total CRM contacts", "Total number of admission contacts", value, delta)


def get_qualified_contacts(from_date=None, to_date=None, user=None):
	value, delta = get_count_delta(
		"CRM Contact", from_date, to_date, user, [["enrollment_status", "=", "Có triển vọng"]]
	)
	return number_chart("Qualified contacts", "Contacts currently in the qualified stage", value, delta)


def get_enrolled_contacts(from_date=None, to_date=None, user=None):
	value, delta = get_count_delta(
		"CRM Contact", from_date, to_date, user, [["enrollment_status", "=", "Đã nhập học"]]
	)
	return number_chart("Enrolled contacts", "Contacts currently in the enrolled stage", value, delta)


def get_admission_trend(from_date=None, to_date=None, user=None):
	students = daily_counts("CRM Student", from_date, to_date)
	contacts = daily_counts("CRM Contact", from_date, to_date, user)
	dates = sorted(set(students) | set(contacts))
	data = [
		{
			"date": date,
			"students": students.get(date, 0),
			"contacts": contacts.get(date, 0),
		}
		for date in dates
	]

	return {
		"data": data,
		"title": _("Admission trend"),
		"subtitle": _("Daily student imports and CRM contact creation"),
		"xAxis": {"title": _("Date"), "key": "date", "type": "time", "timeGrain": "day"},
		"yAxis": {"title": _("Count")},
		"series": [
			{"name": "students", "type": "line", "showDataPoints": True},
			{"name": "contacts", "type": "line", "showDataPoints": True},
		],
	}


def daily_counts(doctype, from_date, to_date, user=None):
	table = DocType(doctype)
	query = (
		frappe.qb.from_(table)
		.select(Date(table.creation).as_("date"), Count(table.name).as_("count"))
		.where(Date(table.creation).between(from_date, to_date))
		.groupby(Date(table.creation))
		.orderby(Date(table.creation))
	)
	if doctype == "CRM Contact" and user:
		query = query.where(table.assigned_to == get_assigned_crm_staff(user))

	return {
		frappe.utils.get_datetime(row.date).strftime("%Y-%m-%d"): row.count or 0
		for row in query.run(as_dict=True)
	}


def get_contacts_by_stage(from_date=None, to_date=None, user=None):
	return donut_chart(
		"CRM Contact",
		"enrollment_status",
		"enrollment_status",
		"Contacts by stage",
		"Current admission pipeline distribution",
		from_date,
		to_date,
		user,
	)


def get_contacts_by_source(from_date=None, to_date=None, user=None):
	return donut_chart(
		"CRM Contact",
		"source",
		"source",
		"Contacts by source",
		"Admission contacts grouped by source",
		from_date,
		to_date,
		user,
	)


def get_students_by_source(from_date=None, to_date=None, user=None):
	return donut_chart(
		"CRM Student",
		"source",
		"source",
		"Students by source",
		"Enrollment students grouped by source",
		from_date,
		to_date,
	)


def get_contacts_by_high_school(from_date=None, to_date=None, user=None):
	return axis_chart(
		"CRM Contact",
		"high_school",
		"high_school",
		"Contacts by high school",
		"Admission contacts grouped by high school",
		from_date,
		to_date,
		user,
	)


def get_contacts_by_assignee(from_date=None, to_date=None, user=None):
	Contact = DocType("CRM Contact")
	CRMStaff = DocType("CRM Staff")
	query = (
		frappe.qb.from_(Contact)
		.left_join(CRMStaff)
		.on(Contact.assigned_to == CRMStaff.name)
		.select(IfNull(CRMStaff.full_name, "Unassigned").as_("assignee"), Count(Contact.name).as_("count"))
		.where(Date(Contact.creation).between(from_date, to_date))
		.groupby(Contact.assigned_to)
	)
	if user:
		query = query.where(Contact.assigned_to == get_assigned_crm_staff(user))

	result = query.run(as_dict=True)
	return {
		"data": result or [],
		"title": _("Contacts by assignee"),
		"subtitle": _("Admission contacts grouped by assigned crm_staff"),
		"xAxis": {"title": _("Assignee"), "key": "assignee", "type": "category"},
		"yAxis": {"title": _("Count")},
		"series": [{"name": "count", "type": "bar"}],
	}


def donut_chart(doctype, fieldname, category_key, title, subtitle, from_date, to_date, user=None):
	data = grouped_counts(doctype, fieldname, category_key, from_date, to_date, user)
	return {
		"data": data,
		"title": _(title),
		"subtitle": _(subtitle),
		"categoryColumn": category_key,
		"valueColumn": "count",
	}


def axis_chart(doctype, fieldname, category_key, title, subtitle, from_date, to_date, user=None):
	data = grouped_counts(doctype, fieldname, category_key, from_date, to_date, user)
	return {
		"data": data,
		"title": _(title),
		"subtitle": _(subtitle),
		"xAxis": {"title": _(title.replace("Contacts by ", "").title()), "key": category_key, "type": "category"},
		"yAxis": {"title": _("Count")},
		"series": [{"name": "count", "type": "bar"}],
	}


def grouped_counts(doctype, fieldname, category_key, from_date, to_date, user=None):
	table = DocType(doctype)
	query = (
		frappe.qb.from_(table)
		.select(IfNull(table[fieldname], "Empty").as_(category_key), Count(table.name).as_("count"))
		.where(Date(table.creation).between(from_date, to_date))
		.groupby(table[fieldname])
	)
	if doctype == "CRM Contact" and user:
		query = query.where(table.assigned_to == get_assigned_crm_staff(user))

	return query.run(as_dict=True) or []
