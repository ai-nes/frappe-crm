from datetime import date, datetime, timedelta

import frappe
from frappe import _
from frappe.utils import get_datetime

from crm.fcrm.student_contact_conversion import contacts_for_student, students_for_contact
from crm.utils import get_docs_by_phone, get_phone_lookup_terms


def _require_authenticated() -> None:
	actor = getattr(getattr(frappe, "session", None), "user", None)
	if not actor or actor in {"Guest", "None"}:
		frappe.throw("Authentication is required.", frappe.PermissionError)


@frappe.whitelist()
def get_student_records_by_phone(phone: str | None = None):
	_require_authenticated()
	if not phone:
		return {
			"students": [],
			"contacts": [],
			"score_histories": [],
			"interactions": [],
			"intents": [],
			"influences": [],
		}

	lookup_terms = get_phone_lookup_terms(phone)

	# 2. Query CRM Student by phone
	students = []
	if lookup_terms:
		students_list = get_docs_by_phone("CRM Lead", phone)

		for s in students_list:
			try:
				doc = frappe.get_doc("CRM Lead", s.name)
				if not doc.has_permission("read"):
					continue
				students.append(doc.as_dict())
			except frappe.DoesNotExistError:
				pass

	student_names = [s["name"] for s in students]

	# 3. Query CRM Contact by phone
	contacts = []
	contact_names = []
	if lookup_terms:
		contacts_list = get_docs_by_phone("CRM Student", phone)

		for c in contacts_list:
			try:
				doc = frappe.get_doc("CRM Student", c.name)
				if not doc.has_permission("read"):
					continue
				contacts.append(doc.as_dict())
				contact_names.append(c.name)
			except frappe.DoesNotExistError:
				pass

	# Fetch contacts linked to the found students as well, ensuring no duplicates
	if student_names:
		linked_contact_names = []
		for student_name in student_names:
			linked_contact_names.extend(contacts_for_student(student_name))
		for contact_name in dict.fromkeys(linked_contact_names):
			if contact_name not in contact_names:
				try:
					doc = frappe.get_doc("CRM Student", contact_name)
					if not doc.has_permission("read"):
						continue
					contacts.append(doc.as_dict())
					contact_names.append(contact_name)
				except frappe.DoesNotExistError:
					pass

	# Fetch linked student names to search for other related entities in case they were not in the phone search
	for c in contacts:
		for linked_student in students_for_contact(c.get("name")):
			if linked_student not in student_names and _can_read_doc("CRM Lead", linked_student):
				try:
					doc = frappe.get_doc("CRM Lead", linked_student)
					students.append(doc.as_dict())
					student_names.append(linked_student)
				except frappe.DoesNotExistError:
					pass

	# 4. Query CRM Score History
	score_histories = []
	if student_names:
		score_histories_list = _scoped_list(
			"CRM Score History",
			filters={"student": ["in", student_names]},
			fields=["name"],
			limit_page_length=0,
		)
		for sh in score_histories_list:
			try:
				doc = frappe.get_doc("CRM Score History", sh.name)
				score_histories.append(doc.as_dict())
			except frappe.DoesNotExistError:
				pass

	# 5. Query CRM Interaction
	interactions = []
	or_filters = []
	if student_names:
		or_filters.append(["student", "in", student_names])
	if contact_names:
		or_filters.append(["crm_contact", "in", contact_names])

	if or_filters:
		interactions_list = _scoped_list(
			"CRM Interaction",
			or_filters=or_filters,
			fields=["name"],
			limit_page_length=0,
		)
		for ix in interactions_list:
			try:
				doc = frappe.get_doc("CRM Interaction", ix.name)
				interactions.append(doc.as_dict())
			except frappe.DoesNotExistError:
				pass

	# 6. Query CRM Intent
	intents = []
	if student_names:
		intents_list = _scoped_list(
			"CRM Intent",
			filters={"student": ["in", student_names]},
			fields=["name"],
			limit_page_length=0,
		)
		for it in intents_list:
			try:
				doc = frappe.get_doc("CRM Intent", it.name)
				intents.append(doc.as_dict())
			except frappe.DoesNotExistError:
				pass

	# 7. Query CRM Influence
	influences = []
	if contact_names:
		influences_list = _scoped_list(
			"CRM Influence",
			filters={"crm_contact": ["in", contact_names]},
			fields=["name"],
			limit_page_length=0,
		)
		for inf in influences_list:
			try:
				doc = frappe.get_doc("CRM Influence", inf.name)
				influences.append(doc.as_dict())
			except frappe.DoesNotExistError:
				pass

	return {
		"students": students,
		"contacts": contacts,
		"score_histories": score_histories,
		"interactions": interactions,
		"intents": intents,
		"influences": influences,
	}


def to_unix(dt):
	if not dt:
		return None
	try:
		return int(get_datetime(dt).timestamp())
	except Exception:
		return None


def to_display_date(dt):
	if not dt:
		return None
	if isinstance(dt, str):
		try:
			dt = get_datetime(dt)
		except Exception:
			return dt
	if isinstance(dt, date | datetime):
		return dt.strftime("%d/%m/%Y")
	return str(dt)


def _can_read_doc(doctype: str, name: str | None) -> bool:
	if not name:
		return False
	try:
		doc = frappe.get_doc(doctype, name)
	except frappe.DoesNotExistError:
		return False
	return doc.has_permission("read")


def _scoped_list(doctype: str, **kwargs):
	"""Read related rows without requiring every role to have every projection DocPerm."""
	try:
		return frappe.get_list(doctype, **kwargs)
	except frappe.PermissionError:
		return []


def _visible_students_for_contact(contact: str | None) -> list[str]:
	"""Return only Student links visible in the current session."""
	return [
		student
		for student in dict.fromkeys(students_for_contact(contact) if contact else [])
		if _can_read_doc("CRM Lead", student)
	]


def _visible_contacts_for_student(student: str | None) -> list[str]:
	"""Return only Contact links visible in the current session."""
	return [
		contact
		for contact in dict.fromkeys(contacts_for_student(student) if student else [])
		if _can_read_doc("CRM Student", contact)
	]


def _score_history_payload(history):
	details = []
	for detail in history.get("details") or []:
		details.append(
			{
				"category": detail.get("category"),
				"rule_id": detail.get("rule_id"),
				"signal": detail.get("signal"),
				"score": detail.get("score") or 0,
				"reason": detail.get("reason"),
			}
		)

	return {
		"name": history.name,
		"student": history.student,
		"score_template": history.score_template,
		"scoring_time": history.scoring_time,
		"scoring_date": history.scoring_date,
		"fit_score": history.fit_score or 0,
		"engagement_score": history.engagement_score or 0,
		"intent_score": history.intent_score or 0,
		"time_decay_score": history.time_decay_score or 0,
		"negative_score": history.negative_score or 0,
		"final_score": history.final_score or 0,
		"score_change": history.score_change or 0,
		"triggered_by_doctype": history.triggered_by_doctype,
		"triggered_by": history.triggered_by,
		"details": details,
	}


@frappe.whitelist()
def get_student_score_context(student: str | None = None, contact: str | None = None, limit: int = 20):
	"""Return full score context for the student/contact detail scoring tab."""
	_require_authenticated()
	if not student and contact:
		if not _can_read_doc("CRM Student", contact):
			frappe.throw("Not permitted", frappe.PermissionError)
		students = _visible_students_for_contact(contact)
		if len(students) != 1:
			frappe.throw(
				_("A Contact is linked to multiple Student cases; select a Student."), frappe.ValidationError
			)
		student = students[0]

	if not student:
		return {
			"student": None,
			"histories": [],
			"latest": None,
			"intents": [],
			"template": None,
		}

	if not _can_read_doc("CRM Lead", student):
		frappe.throw("Not permitted", frappe.PermissionError)

	score_names = _scoped_list(
		"CRM Score History",
		filters={"student": student},
		fields=["name"],
		order_by="scoring_time desc, creation desc",
		limit_page_length=int(limit or 20),
	)
	histories = []
	for row in score_names:
		try:
			histories.append(_score_history_payload(frappe.get_doc("CRM Score History", row.name)))
		except frappe.DoesNotExistError:
			continue

	intents = _scoped_list(
		"CRM Intent",
		filters={"student": student},
		fields=[
			"name",
			"interaction",
			"intent_type",
			"intent_role",
			"importance",
			"confidence",
			"notes",
			"modified",
		],
		order_by="modified desc",
		limit_page_length=100,
	)

	template = None
	latest = histories[0] if histories else None
	if latest and latest.get("score_template"):
		template_doc = frappe.get_doc("CRM Score Template", latest["score_template"])
		template = {
			"name": template_doc.name,
			"template_name": template_doc.template_name,
			"status": template_doc.status,
			"fit_weight": template_doc.fit_weight or 0,
			"engagement_weight": template_doc.engagement_weight or 0,
			"intent_weight": template_doc.intent_weight or 0,
			"start_time": template_doc.start_time,
			"end_time": template_doc.end_time,
		}

	return {
		"student": student,
		"histories": histories,
		"latest": latest,
		"intents": intents,
		"template": template,
	}


@frappe.whitelist()
def get_student_dashboard(
	phone: str | None = None,
	interactionLimit: int = 50,
	suggestedEventLimit: int = 10,
	eventStatus: str | None = None,
):
	_require_authenticated()
	if not phone:
		return {"isSuccess": False, "message": "Thiếu số điện thoại", "data": None}

	lookup_terms = get_phone_lookup_terms(phone)
	if not lookup_terms:
		return {"isSuccess": False, "message": "Số điện thoại không hợp lệ", "data": None}

	# 1. Fetch CRM Lead
	students_list = get_docs_by_phone("CRM Lead", phone)

	student_doc = None
	for s in students_list:
		if not _can_read_doc("CRM Lead", s.name):
			continue
		try:
			student_doc = frappe.get_doc("CRM Lead", s.name)
			break
		except frappe.DoesNotExistError:
			pass

	# 2. Fetch CRM Student
	contact_doc = None
	contacts_list = get_docs_by_phone("CRM Student", phone)

	for c in contacts_list:
		if not _can_read_doc("CRM Student", c.name):
			continue
		try:
			contact_doc = frappe.get_doc("CRM Student", c.name)
			break
		except frappe.DoesNotExistError:
			pass

	# Try to link if only one is found
	if student_doc and not contact_doc:
		linked = _visible_contacts_for_student(student_doc.name)
		if linked:
			try:
				contact_doc = frappe.get_doc("CRM Student", linked[0])
			except frappe.DoesNotExistError:
				pass

	if contact_doc and not student_doc:
		students = _visible_students_for_contact(contact_doc.name)
		if len(students) == 1:
			try:
				student_doc = frappe.get_doc("CRM Lead", students[0])
			except frappe.DoesNotExistError:
				pass

	# Return error if student/contact not found
	if not student_doc and not contact_doc:
		return {"isSuccess": False, "message": "Không tìm thấy học sinh", "data": None}

	linked_students = (
		_visible_students_for_contact(contact_doc.name) if contact_doc and not student_doc else []
	)
	student_name = (
		student_doc.name if student_doc else (linked_students[0] if len(linked_students) == 1 else None)
	)
	contact_name = contact_doc.name if contact_doc else None

	# 3. Fetch related documents
	score_histories = []
	if student_name:
		score_histories_list = _scoped_list(
			"CRM Score History",
			filters={"student": student_name},
			fields=["name"],
			order_by="scoring_time desc",
			limit_page_length=0,
		)
		for sh in score_histories_list:
			try:
				score_histories.append(frappe.get_doc("CRM Score History", sh.name).as_dict())
			except frappe.DoesNotExistError:
				pass

	interactions = []
	or_filters = []
	if student_name:
		or_filters.append(["student", "=", student_name])
	if contact_name:
		or_filters.append(["crm_contact", "=", contact_name])

	if or_filters:
		interactions_list = _scoped_list(
			"CRM Interaction",
			or_filters=or_filters,
			fields=["name"],
			order_by="interaction_datetime desc",
			limit_page_length=0,
		)
		for ix in interactions_list:
			try:
				interactions.append(frappe.get_doc("CRM Interaction", ix.name).as_dict())
			except frappe.DoesNotExistError:
				pass

	intents = []
	if student_name:
		intents_list = _scoped_list(
			"CRM Intent",
			filters={"student": student_name},
			fields=["name"],
			order_by="modified desc",
			limit_page_length=0,
		)
		for it in intents_list:
			try:
				intents.append(frappe.get_doc("CRM Intent", it.name).as_dict())
			except frappe.DoesNotExistError:
				pass

	influences = []
	if contact_name:
		influences_list = _scoped_list(
			"CRM Influence",
			filters={"crm_contact": contact_name},
			fields=["name"],
			limit_page_length=0,
		)
		for inf in influences_list:
			try:
				influences.append(frappe.get_doc("CRM Influence", inf.name).as_dict())
			except frappe.DoesNotExistError:
				pass

	# --- Construct Response Data ---
	full_name = student_doc.student_name if student_doc else (contact_doc.full_name if contact_doc else "")
	email = student_doc.email if student_doc else (contact_doc.email if contact_doc else "")
	phone_val = student_doc.phone if student_doc else (contact_doc.phone if contact_doc else "")

	cohort = ""
	contact_cohort_start = getattr(contact_doc, "cohort_start_year", None) if contact_doc else None
	cohort_source = contact_doc if contact_cohort_start else student_doc
	if cohort_source and getattr(cohort_source, "cohort_start_year", None):
		start = cohort_source.cohort_start_year
		end = cohort_source.cohort_end_year or (start + 4)
		cohort = f"{start}-{end}"
	elif student_doc and student_doc.admission_year:
		cohort = student_doc.admission_year
	else:
		cohort = "2026-2030"

	dob_field = None
	if contact_doc and hasattr(contact_doc, "date_of_birth") and contact_doc.date_of_birth:
		dob_field = contact_doc.date_of_birth
	elif student_doc and hasattr(student_doc, "date_of_birth") and student_doc.date_of_birth:
		dob_field = student_doc.date_of_birth
	date_of_birth = to_display_date(dob_field) if dob_field else "15/08/2007"

	high_school = None
	hs_link = student_doc.high_school if student_doc else (contact_doc.high_school if contact_doc else None)
	prov_link = student_doc.province if student_doc else (contact_doc.province if contact_doc else None)

	if hs_link or prov_link:
		high_school = {"province": prov_link or "", "name": hs_link or ""}

	home_address = None
	ward_link = (student_doc.ward if student_doc else None) or (
		contact_doc.get("ward") if contact_doc else None
	)
	if prov_link or ward_link:
		home_address = {"province": prov_link or "", "district": ward_link or "", "detail": ""}

	academic_records = []
	academic_source = contact_doc if contact_doc and contact_doc.get("academic_results") else student_doc
	if academic_source and hasattr(academic_source, "academic_results"):
		for result in academic_source.academic_results:
			rank_map = {"Giỏi": "Gioi", "Khá": "Kha", "Trung bình": "Trung binh", "Yếu": "Yeu"}
			rank = rank_map.get(result.academic_rank, "Gioi")
			academic_records.append({"year": result.school_year or "", "grade": rank})

	languages = []
	language_source = contact_doc if contact_doc and contact_doc.get("language_certificates") else student_doc
	if language_source and hasattr(language_source, "language_certificates"):
		for cert in language_source.language_certificates:
			languages.append(
				{
					"language": cert.language or "Tiếng Anh",
					"certificate": cert.certificate_name or "IELTS",
					"score": str(cert.score_level) if cert.score_level else "",
					"issuedAt": to_display_date(cert.issue_date) or "",
				}
			)

	interested_programs = []
	contact_program = getattr(contact_doc, "education_program", None) if contact_doc else None
	prog = (
		contact_program
		if contact_program
		else (
			student_doc.education_program
			if student_doc and hasattr(student_doc, "education_program")
			else None
		)
	)
	if prog:
		prog_map = {
			"THPT thường": "thpt_thuong",
			"THPT chuyên": "thpt_chuyen",
			"Quốc tế": "quoc_te",
			"Song ngữ": "song_ngu",
		}
		interested_programs.append(prog_map.get(prog, "quoc_te"))
	else:
		interested_programs = ["quoc_te"]

	interested_majors = []
	major_link = contact_doc.major if contact_doc else (student_doc.major if student_doc else None)
	if major_link:
		major_map = {
			"Software Engineering": "cntt",
			"Computer Science": "cntt",
			"Kinh tế quốc tế": "kinh_te_quoc_te",
			"Marketing": "marketing",
		}
		interested_majors.append({"major": major_map.get(major_link, "cntt"), "priority": "primary"})
	else:
		interested_majors = [{"major": "cntt", "priority": "primary"}]

	social_media_interests = [
		{
			"platform": "facebook",
			"isFollowing": True,
			"engagementLevel": "high",
			"handle": f"facebook.com/{full_name.lower().replace(' ', '.')}",
			"lastActivityAt": to_unix(contact_doc.modified if contact_doc else datetime.now()),
			"recentActivities": ["Comment bài tuyển sinh 2026"],
		}
	]

	notes = contact_doc.notes if contact_doc else (student_doc.notes if student_doc else "")

	student_data = {
		"id": student_name or contact_name or 1001,
		"fullName": full_name,
		"email": email,
		"phone": phone_val,
		"cohort": cohort,
		"dateOfBirth": date_of_birth,
		"highSchool": high_school,
		"homeAddress": home_address,
		"academicRecords": academic_records,
		"languages": languages,
		"interestedPrograms": interested_programs,
		"interestedMajors": interested_majors,
		"socialMediaInterests": social_media_interests,
		"notes": notes,
	}

	intent_key_map = {
		"Major Inquiry": "major_inquiry",
		"Tuition": "tuition_inquiry",
		"Tuition Inquiry": "tuition_inquiry",
		"Scholarship": "scholarship_inquiry",
		"Scholarship Inquiry": "scholarship_inquiry",
		"Admission Process": "admission_process",
		"Campus Visit Inquiry": "campus_visit_inquiry",
		"Student Life Inquiry": "student_life_inquiry",
		"Application Submission": "application_submission",
		"Enrollment Intent": "enrollment_intent",
		"Enrollment Inquiry": "enrollment_intent",
		"Deposit Intent": "deposit_intent",
	}
	intent_type_map = {
		"major_inquiry": "academic",
		"tuition_inquiry": "financial",
		"scholarship_inquiry": "financial",
		"admission_process": "admission",
		"campus_visit_inquiry": "campus_life",
		"student_life_inquiry": "campus_life",
		"application_submission": "admission",
		"enrollment_intent": "admission",
		"deposit_intent": "admission",
	}

	# --- Interactions Mapping ---
	interaction_items = []
	for ix in interactions:
		type_map = {
			"Form Submission": "form_submission",
			"Event Attendance": "event_attendance",
			"Application Submission": "application_submission",
			"Admission Counseling": "conversation",
			"Phone Call": "phone_call",
			"Email": "email",
			"Payment": "payment",
		}
		ix_type = type_map.get(ix.get("interaction_type"), "conversation")

		ix_intents = []
		ix_dominant_intent = None
		for intent in intents:
			if intent.get("interaction") == ix.get("name"):
				key = intent_key_map.get(intent.get("intent_type"), "admission_inquiry")
				role = intent.get("intent_role") or "Support"
				ix_intents.append({"key": key, "role": role})
				if role == "Dominant":
					ix_dominant_intent = key

		interaction_items.append(
			{
				"id": ix.get("name"),
				"type": ix_type,
				"title": ix.get("summary") or ix.get("interaction_type") or "Tương tác",
				"summary": ix.get("notes") or ix.get("summary") or "",
				"occurredAt": to_unix(ix.get("interaction_datetime")),
				"channel": ix.get("interaction_type") or "",
				"intents": ix_intents,
				"dominantIntent": ix_dominant_intent,
				"supportIntents": [i["key"] for i in ix_intents if i["role"] == "Support"],
				"metadata": {"conversationId": ix.get("name")},
			}
		)

	interaction_items = sorted(interaction_items, key=lambda x: x["occurredAt"] or 0, reverse=True)
	interaction_items = interaction_items[: int(interactionLimit)]

	# --- Intents Mapping ---
	intent_items = []
	for intent in intents:
		key = intent_key_map.get(intent.get("intent_type"), "admission_inquiry")

		intent_type = intent_type_map.get(key, "admission")

		importance_map = {"Very High": "very_high", "High": "high", "Medium": "medium", "Low": "low"}
		importance = importance_map.get(intent.get("importance"), "medium")

		confidence = (intent.get("confidence") / 100.0) if intent.get("confidence") else None

		role = intent.get("intent_role") or "Support"
		intent_items.append(
			{
				"key": key,
				"label": intent.get("intent_type") or "Ý định",
				"intentType": intent_type,
				"importance": importance,
				"role": role,
				"isDominant": role == "Dominant",
				"detectedAt": to_unix(intent.get("modified")),
				"sourceInteractionId": intent.get("interaction") or "",
				"sourceType": "conversation",
				"confidence": confidence,
			}
		)

	# --- Events Mapping ---
	event_items = []
	attended_event_names = []

	participation_status_map = {
		"Registered": "registered",
		"Checked-in": "attended",
		"No-show": "no_show",
		"Feedback Given": "feedback_given",
	}

	if contact_doc:
		participations = list(
			_scoped_list(
				"CRM Marketing Engagement",
				filters={"crm_contact": contact_doc.name, "engagement_kind": "event_participation"},
				fields=["name", "crm_event", "status", "registered_at", "checked_in_at"],
				order_by="registered_at desc",
				limit_page_length=0,
			)
		)
		participations.sort(key=lambda row: str(row.registered_at or ""), reverse=True)
		for participation in participations:
			try:
				evt_doc = frappe.get_doc("CRM Event", participation.crm_event)
			except frappe.DoesNotExistError:
				continue
			event_items.append(
				{
					"id": evt_doc.name,
					"name": evt_doc.title or evt_doc.name,
					"type": "open_day",
					"attendedAt": to_unix(participation.checked_in_at)
					or to_unix(participation.registered_at)
					or to_unix(evt_doc.start_datetime or evt_doc.event_date)
					or to_unix(evt_doc.creation),
					"status": participation_status_map.get(participation.status, "registered"),
				}
			)
			attended_event_names.append(evt_doc.name)

		# Fallback for contacts predating the Phase 5 many-to-many migration
		legacy_event = getattr(contact_doc, "crm_event", None)
		if not participations and legacy_event:
			try:
				evt_doc = frappe.get_doc("CRM Event", legacy_event)
				event_items.append(
					{
						"id": evt_doc.name,
						"name": evt_doc.title or evt_doc.name,
						"type": "open_day",
						"attendedAt": to_unix(evt_doc.start_datetime or evt_doc.event_date)
						or to_unix(evt_doc.creation),
						"status": "attended",
					}
				)
				attended_event_names.append(evt_doc.name)
			except frappe.DoesNotExistError:
				pass

	# --- Suggested Events Mapping ---
	suggested_event_items = []
	upcoming_evts = _scoped_list(
		"CRM Event",
		fields=["name", "title", "event_date", "start_datetime", "notes"],
		limit_page_length=0,
	)

	for ue in upcoming_evts:
		if ue.name not in attended_event_names:
			suggested_event_items.append(
				{
					"id": ue.name,
					"name": ue.title or ue.name,
					"type": "open_day",
					"startsAt": to_unix(ue.start_datetime or ue.event_date)
					or to_unix(datetime.now() + timedelta(days=5)),
					"matchScore": 90,
					"matchReason": "Phù hợp ngành học CNTT",
				}
			)

	suggested_event_items = suggested_event_items[: int(suggestedEventLimit)]

	# --- Lead Score Mapping ---
	lead_score = None
	if score_histories:
		latest_score_history = score_histories[0]
		total_score = latest_score_history.get("final_score") or 0
		if total_score >= 80:
			tier = "hot"
		elif total_score >= 50:
			tier = "warm"
		else:
			tier = "cold"

		breakdown = []
		details_list = latest_score_history.get("details") or []
		for det in details_list:
			breakdown.append(
				{
					"label": det.get("signal") or det.get("reason") or "Điểm tiềm năng",
					"points": det.get("score") or 0,
					"category": (det.get("category") or "fit").lower(),
				}
			)

		trend = []
		sorted_histories = sorted(score_histories, key=lambda x: x.get("scoring_time") or "")
		for sh in sorted_histories[-5:]:
			sc_time = sh.get("scoring_time")
			date_str = ""
			if sc_time:
				dt_obj = get_datetime(sc_time)
				date_str = dt_obj.strftime("%d/%m")
			trend.append({"date": date_str, "score": sh.get("final_score") or 0})

		lead_score = {
			"fitScore": latest_score_history.get("fit_score") or 0,
			"engagementScore": latest_score_history.get("engagement_score") or 0,
			"intentScore": latest_score_history.get("intent_score") or 0,
			"timeDecayScore": latest_score_history.get("time_decay_score") or 0,
			"negativeScore": latest_score_history.get("negative_score") or 0,
			"totalScore": total_score,
			"maxScore": 100,
			"tier": tier,
			"isPotentialCustomer": total_score >= 70,
			"breakdown": breakdown,
			"trend": trend,
			"lastUpdated": to_unix(latest_score_history.get("scoring_time")),
		}
	else:
		lead_score = {
			"fitScore": 0,
			"engagementScore": 0,
			"intentScore": 0,
			"timeDecayScore": 0,
			"negativeScore": 0,
			"totalScore": 0,
			"maxScore": 100,
			"tier": "cold",
			"isPotentialCustomer": False,
			"breakdown": [],
			"trend": [],
			"lastUpdated": to_unix(datetime.now()),
		}

	return {
		"isSuccess": True,
		"message": "Thành công",
		"data": {
			"student": student_data,
			"interactions": {"items": interaction_items, "nextCursor": None},
			"intents": {
				"items": intent_items,
				"total": len(intent_items),
				"dominant": [i for i in intent_items if i.get("isDominant")],
				"support": [i for i in intent_items if not i.get("isDominant")],
			},
			"events": {"items": event_items},
			"suggestedEvents": {"items": suggested_event_items},
			"leadScore": lead_score,
		},
		"metadata": None,
	}


@frappe.whitelist(allow_guest=True)  # nosemgrep: security.guest-whitelisted-method
def get_training_programs():
	return {
		"isSuccess": True,
		"message": "Thành công",
		"data": {
			"items": [
				{"key": "thpt_thuong", "label": "THPT thường"},
				{"key": "thpt_chuyen", "label": "THPT chuyên"},
				{"key": "quoc_te", "label": "Quốc tế"},
				{"key": "song_ngu", "label": "Song ngữ"},
				{"key": "cao_dang_lien_thong", "label": "Cao đẳng liên thông"},
				{"key": "gdtx", "label": "Giáo dục thường xuyên"},
			]
		},
		"metadata": None,
	}


@frappe.whitelist(allow_guest=True)  # nosemgrep: security.guest-whitelisted-method
def get_study_majors():
	return {
		"isSuccess": True,
		"message": "Thành công",
		"data": {
			"items": [
				{"key": "cntt", "label": "Công nghệ thông tin"},
				{"key": "kinh_te", "label": "Kinh tế"},
				{"key": "kinh_te_quoc_te", "label": "Kinh tế quốc tế"},
				{"key": "quan_tri_kinh_doanh", "label": "Quản trị kinh doanh"},
				{"key": "marketing", "label": "Marketing"},
				{"key": "tai_chinh_ngan_hang", "label": "Tài chính ngân hàng"},
				{"key": "luat", "label": "Luật"},
				{"key": "ngoai_ngu", "label": "Ngoại ngữ"},
				{"key": "thiet_ke_do_hoa", "label": "Thiết kế đồ họa"},
				{"key": "y_duoc", "label": "Y dược"},
				{"key": "kiem_toan", "label": "Kiểm toán"},
			]
		},
		"metadata": None,
	}


@frappe.whitelist(allow_guest=True)  # nosemgrep: security.guest-whitelisted-method
def get_intent_definitions():
	return {
		"isSuccess": True,
		"message": "Thành công",
		"data": {
			"items": [
				{
					"key": "admission_inquiry",
					"label": "Hỏi tuyển sinh",
					"intentType": "admission",
					"importance": "very_high",
				},
				{
					"key": "eligibility_check",
					"label": "Kiểm tra điều kiện nhập học",
					"intentType": "academic",
					"importance": "high",
				},
				{
					"key": "scholarship_inquiry",
					"label": "Hỏi học bổng",
					"intentType": "financial",
					"importance": "very_high",
				},
				{
					"key": "tuition_inquiry",
					"label": "Hỏi học phí",
					"intentType": "financial",
					"importance": "high",
				},
				{
					"key": "application_submission",
					"label": "Nộp hồ sơ tuyển sinh",
					"intentType": "admission",
					"importance": "very_high",
				},
				{
					"key": "admission_process",
					"label": "Hỏi quy trình xét tuyển",
					"intentType": "admission",
					"importance": "very_high",
				},
				{
					"key": "enrollment_intent",
					"label": "Ý định nhập học",
					"intentType": "admission",
					"importance": "very_high",
				},
				{
					"key": "deposit_intent",
					"label": "Ý định đặt cọc",
					"intentType": "admission",
					"importance": "very_high",
				},
				{
					"key": "career_exploration",
					"label": "Tìm hiểu định hướng nghề nghiệp",
					"intentType": "career",
					"importance": "medium",
				},
				{
					"key": "major_inquiry",
					"label": "Hỏi ngành học",
					"intentType": "academic",
					"importance": "high",
				},
				{
					"key": "major_comparison",
					"label": "So sánh các ngành học",
					"intentType": "academic",
					"importance": "medium",
				},
				{
					"key": "university_comparison",
					"label": "So sánh các trường đại học",
					"intentType": "career",
					"importance": "medium",
				},
				{
					"key": "event_registration",
					"label": "Đăng ký sự kiện",
					"intentType": "campus_life",
					"importance": "high",
				},
				{
					"key": "campus_visit_inquiry",
					"label": "Hỏi tham quan cơ sở",
					"intentType": "campus_life",
					"importance": "high",
				},
				{
					"key": "student_life_inquiry",
					"label": "Hỏi đời sống sinh viên",
					"intentType": "campus_life",
					"importance": "medium",
				},
				{
					"key": "international_program_inquiry",
					"label": "Hỏi chương trình quốc tế",
					"intentType": "academic",
					"importance": "high",
				},
				{
					"key": "complaint_support",
					"label": "Yêu cầu hỗ trợ/khiếu nại",
					"intentType": "support",
					"importance": "medium",
				},
			]
		},
		"metadata": None,
	}
