import json
from datetime import datetime, timedelta

import frappe
from frappe.utils.telemetry import capture

from crm.fcrm.doctype.crm_student.enrollment_transition import set_enrollment_status

DEMO_STATE_KEY = "crm_demo_data_created"
DEMO_STUDENTS_KEY = "crm_demo_students"
DEMO_CONTACTS_KEY = "crm_demo_crm_contacts"
DEMO_NOTES_KEY = "crm_demo_notes"
DEMO_TASKS_KEY = "crm_demo_tasks"
DEMO_CALL_LOGS_KEY = "crm_demo_call_logs"
DEMO_INTERACTIONS_KEY = "crm_demo_interactions"
DEMO_SCORE_TEMPLATES_KEY = "crm_demo_score_templates"
DEMO_SCORE_HISTORIES_KEY = "crm_demo_score_histories"
_DEMO_SCORE_TEMPLATE_OWNED = False

DEMO_STUDENTS = [
	{
		"student_name": "Minh Anh Nguyen",
		"phone": "0901100001",
		"email": "minhanh.demo@example.com",
		"source": "Website",
		"scores": [54, 63, 72],
	},
	{
		"student_name": "Gia Bao Tran",
		"phone": "0901100002",
		"email": "giabao.demo@example.com",
		"source": "Open Day",
		"scores": [48, 56, 61],
	},
	{
		"student_name": "Linh Chi Pham",
		"phone": "0901100003",
		"email": "linhchi.demo@example.com",
		"source": "Facebook",
		"scores": [60, 68, 77],
	},
]


def create_demo_data(_args: dict | None = None):
	if frappe.db.get_default(DEMO_STATE_KEY):
		return

	from crm.demo.users import create_demo_users

	demo_users = create_demo_users()
	student_names = _create_demo_students()
	contact_names = _create_demo_contacts(student_names)
	interaction_names = _create_demo_interactions(student_names, contact_names)
	template_name = _ensure_score_template()
	score_template_names = [template_name] if _DEMO_SCORE_TEMPLATE_OWNED else []
	score_history_names = _create_demo_score_histories(student_names)
	note_names = _create_demo_notes(contact_names)
	task_names = _create_demo_tasks(contact_names, demo_users)
	call_log_names = _create_demo_call_logs(contact_names)

	frappe.db.set_default(DEMO_STUDENTS_KEY, json.dumps(student_names))
	frappe.db.set_default(DEMO_CONTACTS_KEY, json.dumps(contact_names))
	frappe.db.set_default(DEMO_INTERACTIONS_KEY, json.dumps(interaction_names))
	frappe.db.set_default(DEMO_SCORE_TEMPLATES_KEY, json.dumps(score_template_names))
	frappe.db.set_default(DEMO_SCORE_HISTORIES_KEY, json.dumps(score_history_names))
	frappe.db.set_default(DEMO_NOTES_KEY, json.dumps(note_names))
	frappe.db.set_default(DEMO_TASKS_KEY, json.dumps(task_names))
	frappe.db.set_default(DEMO_CALL_LOGS_KEY, json.dumps(call_log_names))
	frappe.db.set_default(DEMO_STATE_KEY, "1")

	capture("demo_data_created", "crm")


@frappe.whitelist()
def clear_demo_data():
	frappe.only_for("System Manager", True)

	if not frappe.db.get_default(DEMO_STATE_KEY):
		return

	from crm.demo.users import DEMO_USER_EMAILS, delete_demo_users

	student_names = json.loads(frappe.db.get_default(DEMO_STUDENTS_KEY) or "[]")
	contact_names = json.loads(frappe.db.get_default(DEMO_CONTACTS_KEY) or "[]")
	note_names = json.loads(frappe.db.get_default(DEMO_NOTES_KEY) or "[]")
	task_names = json.loads(frappe.db.get_default(DEMO_TASKS_KEY) or "[]")
	call_log_names = json.loads(frappe.db.get_default(DEMO_CALL_LOGS_KEY) or "[]")
	interaction_names = json.loads(frappe.db.get_default(DEMO_INTERACTIONS_KEY) or "[]")
	score_template_names = json.loads(frappe.db.get_default(DEMO_SCORE_TEMPLATES_KEY) or "[]")
	score_history_names = json.loads(frappe.db.get_default(DEMO_SCORE_HISTORIES_KEY) or "[]")

	_delete_docs("CRM Score History", score_history_names)
	_delete_docs("Call Log", call_log_names)
	_delete_docs("Task", task_names)
	_delete_docs("FCRM Note", note_names)
	_delete_docs("CRM Interaction", interaction_names)
	_delete_docs("CRM Contact", contact_names)
	_delete_docs("CRM Student", student_names)
	_delete_docs("CRM Score Template", score_template_names)
	delete_demo_users(DEMO_USER_EMAILS)

	for key in (
		DEMO_STUDENTS_KEY,
		DEMO_CONTACTS_KEY,
		DEMO_INTERACTIONS_KEY,
		DEMO_SCORE_TEMPLATES_KEY,
		DEMO_SCORE_HISTORIES_KEY,
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
		existing = frappe.db.get_value(
			"CRM Student", {"email": data["email"]}, ["name", "email"], as_dict=True
		) or frappe.db.get_value("CRM Student", {"phone": data["phone"]}, ["name", "email"], as_dict=True)
		if existing:
			if not existing.email:
				frappe.db.set_value("CRM Student", existing.name, "email", data["email"], update_modified=False)
			names.append(existing.name)
			continue

		doc = frappe.get_doc(
			{
				"doctype": "CRM Student",
				"student_name": data["student_name"],
				"phone": data["phone"],
				"email": data["email"],
				"enrollment_status": "Mới",
				"source": _ensure_source(data["source"]),
			}
		)
		previous_flag = getattr(frappe.flags, "student_intake_service", False)
		frappe.flags.student_intake_service = True
		try:
			doc.insert(ignore_permissions=True)
		finally:
			frappe.flags.student_intake_service = previous_flag
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

		enrollment_status = ("Mới", "Có triển vọng", "Đã xác nhận")[index % 3]
		doc = frappe.get_doc(
			{
				"doctype": "CRM Contact",
				"full_name": student.student_name,
				"phone": student.phone,
				"email": student.email,
				"enrollment_status": enrollment_status,
				"student": student.name,
				"source": student.source,
				"high_school": student.high_school,
				"province": student.province,
				"major": student.major,
				"aspiration": student.aspiration,
				"admission_year": student.admission_year,
				"branch": student.branch,
				"education_program": student.education_program,
				"cohort_start_year": student.cohort_start_year,
				"cohort_end_year": student.cohort_end_year,
				"graduation_score": student.graduation_score,
				"transcript_score": student.transcript_score,
				"admission_method": student.admission_method,
				"english_converted_score": student.english_converted_score,
				"total_score": student.total_score,
				"notes": "Demo admission pipeline contact",
			}
		).insert(ignore_permissions=True)
		set_enrollment_status(student.name, "Đã chuyển đổi", source="demo_seed")
		_backdate("CRM Contact", doc.name, len(names) + 5)
		names.append(doc.name)

	return names


def _create_demo_interactions(student_names, contact_names):
	names = []
	for index, (student_name, contact_name) in enumerate(zip(student_names, contact_names, strict=False)):
		student = frappe.get_doc("CRM Student", student_name)
		contact = frappe.get_doc("CRM Contact", contact_name)
		interaction_type = _ensure_interaction_type("Admission Counseling")
		for offset, outcome in enumerate(("Captured", "Follow Up Needed")):
			summary = f"{student.student_name} {outcome.lower()} via {student.source or 'Website'}"
			existing = frappe.db.exists(
				"CRM Interaction",
				{
					"student": student.name,
					"crm_contact": contact.name,
					"summary": summary,
				},
			)
			if existing:
				names.append(existing)
				continue

			doc = frappe.get_doc(
				{
					"doctype": "CRM Interaction",
					"student": student.name,
					"crm_contact": contact.name,
					"interaction_type": interaction_type,
					"interaction_datetime": datetime.now() - timedelta(days=index + offset + 2),
					"outcome": outcome,
					"summary": summary,
					"notes": "Demo interaction for admissions scoring and counselor follow-up.",
				}
			).insert(ignore_permissions=True)
			_backdate("CRM Interaction", doc.name, index + offset + 2)
			names.append(doc.name)

	return names


def _create_demo_score_histories(student_names):
	names = []
	template = _ensure_score_template()
	for index, student_name in enumerate(student_names):
		score_series = DEMO_STUDENTS[index].get("scores", [])
		for offset, final_score in enumerate(score_series):
			scoring_time = datetime.now() - timedelta(days=(len(score_series) - offset) * 3)
			existing = frappe.db.exists(
				"CRM Score History",
				{
					"student": student_name,
					"score_template": template,
					"final_score": final_score,
				},
			)
			if existing:
				names.append(existing)
				continue

			doc = frappe.get_doc(
				{
					"doctype": "CRM Score History",
					"student": student_name,
					"score_template": template,
					"scoring_time": scoring_time,
					"fit_score": final_score * 0.35,
					"engagement_score": final_score * 0.25,
					"intent_score": final_score * 0.25,
					"time_decay_score": final_score * 0.1,
					"negative_score": -(100 - final_score) * 0.05,
					"final_score": final_score,
					"details": [
						{
							"category": "Fit",
							"rule_id": "fit.major",
							"signal": "Major and campus fit",
							"score": final_score * 0.35,
							"reason": "Student profile matches preferred program and campus.",
						},
						{
							"category": "Engagement",
							"rule_id": "engagement.follow_up",
							"signal": "Recent admission interaction",
							"score": final_score * 0.25,
							"reason": "Student has recent interactions with counselor.",
						},
					],
				}
			).insert(ignore_permissions=True)
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
				"doctype": "Task",
				"title": "Follow up application documents",
				"priority": "Medium",
				"status": "Todo",
				"assigned_to": assigned_to,
				"reference_doctype": "CRM Contact",
				"reference_docname": contact_name,
			}
		).insert(ignore_permissions=True)
		_backdate("Task", doc.name, len(names) + 2)
		names.append(doc.name)

	return names


def _create_demo_call_logs(contact_names):
	names = []
	for contact_name in contact_names:
		contact = frappe.get_doc("CRM Contact", contact_name)
		doc = frappe.get_doc(
			{
				"doctype": "Call Log",
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
		_backdate("Call Log", doc.name, len(names) + 1)
		names.append(doc.name)

	return names


def _ensure_source(source):
	if frappe.db.exists("CRM Lead Source", source):
		return source

	return frappe.get_doc({"doctype": "CRM Lead Source", "source_name": source}).insert(
		ignore_permissions=True
	).name


def _ensure_interaction_type(name):
	if frappe.db.exists("CRM Term", name):
		return name

	return frappe.get_doc(
		{
			"doctype": "CRM Term",
			"term_name": name,
			"category": "interaction_type",
			"description": "Admissions counselor interaction.",
		}
	).insert(ignore_permissions=True).name


def _ensure_score_template():
	global _DEMO_SCORE_TEMPLATE_OWNED
	template_name = "Default Admission Scoring"
	existing = frappe.db.get_value("CRM Score Template", {"template_name": template_name}, "name") or frappe.db.get_value(
		"CRM Score Template", {"status": "Active"}, "name"
	)
	if existing:
		_DEMO_SCORE_TEMPLATE_OWNED = False
		return existing

	_DEMO_SCORE_TEMPLATE_OWNED = True
	return frappe.get_doc(
		{
			"doctype": "CRM Score Template",
			"template_name": template_name,
			"status": "Active",
			"start_time": datetime.now() - timedelta(days=30),
			"fit_scoring": '{"major_fit": 35, "campus_fit": 15}',
			"engagement_scoring": '{"recent_interaction": 25}',
			"intent_scoring": '{"high_intent": 25}',
			"time_decay_scoring": '{"half_life_days": 14}',
			"negative_scoring": '{"no_response": -10, "wrong_target": -30}',
		}
	).insert(ignore_permissions=True).name


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
