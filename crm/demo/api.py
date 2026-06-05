import json
from datetime import datetime, timedelta

import frappe
from frappe.utils.telemetry import capture

DEMO_STATE_KEY = "crm_demo_data_created"
DEMO_STUDENTS_KEY = "crm_demo_students"
DEMO_CONTACTS_KEY = "crm_demo_crm_contacts"
DEMO_NOTES_KEY = "crm_demo_notes"
DEMO_TASKS_KEY = "crm_demo_tasks"
DEMO_CALL_LOGS_KEY = "crm_demo_call_logs"

DEMO_STUDENTS = [
	{
		"student_name": "Minh Anh Nguyen",
		"mobile_no": "+84 901 100 001",
		"email": "minhanh.demo@example.com",
		"source": "Website",
	},
	{
		"student_name": "Gia Bao Tran",
		"mobile_no": "+84 901 100 002",
		"email": "giabao.demo@example.com",
		"source": "Open Day",
	},
	{
		"student_name": "Linh Chi Pham",
		"mobile_no": "+84 901 100 003",
		"email": "linhchi.demo@example.com",
		"source": "Facebook",
	},
]


def create_demo_data(_args: dict | None = None):
	if frappe.db.get_default(DEMO_STATE_KEY):
		return

	from crm.demo.users import create_demo_users

	demo_users = create_demo_users()
	student_names = _create_demo_students()
	contact_names = _create_demo_contacts(student_names)
	note_names = _create_demo_notes(contact_names)
	task_names = _create_demo_tasks(contact_names, demo_users)
	call_log_names = _create_demo_call_logs(contact_names)

	frappe.db.set_default(DEMO_STUDENTS_KEY, json.dumps(student_names))
	frappe.db.set_default(DEMO_CONTACTS_KEY, json.dumps(contact_names))
	frappe.db.set_default(DEMO_NOTES_KEY, json.dumps(note_names))
	frappe.db.set_default(DEMO_TASKS_KEY, json.dumps(task_names))
	frappe.db.set_default(DEMO_CALL_LOGS_KEY, json.dumps(call_log_names))
	frappe.db.set_default(DEMO_STATE_KEY, "1")

	capture("demo_data_created", "crm")


@frappe.whitelist()
def clear_demo_data():
	frappe.only_for(["Sales Manager", "System Manager"], True)

	if not frappe.db.get_default(DEMO_STATE_KEY):
		return

	from crm.demo.users import DEMO_USER_EMAILS, delete_demo_users

	student_names = json.loads(frappe.db.get_default(DEMO_STUDENTS_KEY) or "[]")
	contact_names = json.loads(frappe.db.get_default(DEMO_CONTACTS_KEY) or "[]")
	note_names = json.loads(frappe.db.get_default(DEMO_NOTES_KEY) or "[]")
	task_names = json.loads(frappe.db.get_default(DEMO_TASKS_KEY) or "[]")
	call_log_names = json.loads(frappe.db.get_default(DEMO_CALL_LOGS_KEY) or "[]")

	_delete_docs("CRM Call Log", call_log_names)
	_delete_docs("CRM Task", task_names)
	_delete_docs("FCRM Note", note_names)
	_delete_docs("CRM Contact", contact_names)
	_delete_docs("CRM Student", student_names)
	delete_demo_users(DEMO_USER_EMAILS)

	for key in (
		DEMO_STUDENTS_KEY,
		DEMO_CONTACTS_KEY,
		DEMO_NOTES_KEY,
		DEMO_TASKS_KEY,
		DEMO_CALL_LOGS_KEY,
		DEMO_STATE_KEY,
	):
		frappe.db.set_default(key, None)

	capture("demo_data_cleared", "crm")


@frappe.whitelist()
def get_demo_state():
	return {"demo_data_created": bool(frappe.db.get_default(DEMO_STATE_KEY))}


def _create_demo_students():
	names = []
	for data in DEMO_STUDENTS:
		existing = frappe.db.exists("CRM Student", {"email": data["email"]})
		if existing:
			names.append(existing)
			continue

		doc = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": data["student_name"],
				"mobile_no": data["mobile_no"],
				"email": data["email"],
				"enrollment_status": "Pending Confirmation",
				"converted": 0,
				"source": _ensure_source(data["source"]),
			}
		).insert(ignore_permissions=True)
		_backdate("CRM Student", doc.name, len(names) + 8)
		names.append(doc.name)

	return names


def _create_demo_contacts(student_names):
	names = []
	for index, student_name in enumerate(student_names):
		student = frappe.get_doc("CRM Student", student_name)
		existing = frappe.db.exists("CRM Contact", {"student": student.name})
		if existing:
			names.append(existing)
			continue

		stage = ("Interested", "Qualified", "Enrolled")[index % 3]
		doc = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"full_name": student.student_name,
				"phone": student.mobile_no,
				"email": student.email,
				"stage": stage,
				"student": student.name,
				"source": student.source,
				"notes": "Demo admission pipeline contact",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Student", student.name, "converted", 1, update_modified=False)
		_backdate("CRM Contact", doc.name, len(names) + 5)
		names.append(doc.name)

	return names


def _create_demo_notes(contact_names):
	names = []
	for contact_name in contact_names:
		doc = frappe.get_doc(
			{
				"doctype": "FCRM Note",
				"title": "Admission counseling note",
				"content": "Discussed program fit, intake timeline, and next documents.",
				"reference_doctype": "CRM Contact",
				"reference_docname": contact_name,
			}
		).insert(ignore_permissions=True)
		_backdate("FCRM Note", doc.name, len(names) + 3)
		names.append(doc.name)

	return names


def _create_demo_tasks(contact_names, demo_users):
	names = []
	assigned_to = demo_users[0] if demo_users else frappe.session.user
	for contact_name in contact_names:
		doc = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Follow up application documents",
				"priority": "Medium",
				"status": "Todo",
				"assigned_to": assigned_to,
				"reference_doctype": "CRM Contact",
				"reference_docname": contact_name,
			}
		).insert(ignore_permissions=True)
		_backdate("CRM Task", doc.name, len(names) + 2)
		names.append(doc.name)

	return names


def _create_demo_call_logs(contact_names):
	names = []
	for contact_name in contact_names:
		contact = frappe.get_doc("CRM Contact", contact_name)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"from": contact.phone,
				"to": "+84 280 100 0000",
				"type": "Incoming",
				"status": "Completed",
				"duration": 180,
				"start_time": datetime.now() - timedelta(days=len(names) + 1),
				"reference_doctype": "CRM Contact",
				"reference_docname": contact.name,
			}
		).insert(ignore_permissions=True)
		_backdate("CRM Call Log", doc.name, len(names) + 1)
		names.append(doc.name)

	return names


def _ensure_source(source):
	if frappe.db.exists("CRM Lead Source", source):
		return source

	return frappe.get_doc({"doctype": "CRM Lead Source", "source_name": source}).insert(
		ignore_permissions=True
	).name


def _delete_docs(doctype, names):
	for name in names:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)


def _backdate(doctype, name, days_ago):
	ts = datetime.now() - timedelta(days=days_ago)
	frappe.db.set_value(
		doctype,
		name,
		{"creation": ts, "modified": ts, "modified_by": frappe.session.user},
		update_modified=False,
	)
