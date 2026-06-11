from __future__ import annotations

from datetime import datetime, timedelta

import frappe


SAMPLE_EMAIL = "nguyen.minh.khang.fptu2026@example.com"
SAMPLE_PHONE = "+84 912 345 678"
SAMPLE_STUDENT_NAME = "Nguyen Minh Khang"
SAMPLE_PROVINCE_CODE = "79"
SAMPLE_PROVINCE_NAME = "Ho Chi Minh City"
SAMPLE_WARD_CODE = "760"
SAMPLE_WARD_NAME = "Ben Nghe Ward"
SAMPLE_CAMPUS = "FPTU Ho Chi Minh Campus"
SAMPLE_MAJOR = "Software Engineering"
SAMPLE_MAJOR_CODE = "SE"
SAMPLE_HIGH_SCHOOL = "Tran Dai Nghia High School for the Gifted"
SAMPLE_CAMPAIGN = "FPTU 2026 Admission Campaign - HCMC"
SAMPLE_EVENT = "FPTU HCMC Campus Visit - June 2026"


def execute():
	admission_context = _ensure_admission_context()
	student = _ensure_student()
	contact = _ensure_contact(student)
	interactions = _ensure_interactions(student, contact)
	intents = _ensure_intents(interactions)
	score_template = _ensure_score_template()
	score_histories = _ensure_score_histories(student, score_template)

	frappe.db.commit()

	return {
		"admission_context": admission_context,
		"student": student.name,
		"contact": contact.name,
		"interactions": interactions,
		"intents": intents,
		"score_template": score_template,
		"score_histories": score_histories,
	}


def _ensure_student():
	existing = frappe.db.exists("CRM Student", {"email": SAMPLE_EMAIL})
	if existing:
		student = frappe.get_doc("CRM Student", existing)
		_apply_student_fields(student)
		student.save(ignore_permissions=True)
		return student

	student = frappe.get_doc({
		"doctype": "CRM Student",
	})
	_apply_student_fields(student)
	student.insert(ignore_permissions=True)
	return student


def _apply_student_fields(student):
	student.update({
		"student_name": SAMPLE_STUDENT_NAME,
		"mobile_no": SAMPLE_PHONE,
		"email": SAMPLE_EMAIL,
		"enrollment_status": _ensure_enrollment_status("Confirmed"),
		"enrollment_date": frappe.utils.add_days(frappe.utils.today(), 14),
		"converted": 1,
		"high_school": _ensure_high_school(),
		"province": _ensure_province(),
		"ward": _ensure_ward(),
		"branch": _ensure_default_campus(),
		"major": _ensure_major(),
		"aspiration": _ensure_aspiration("NV1", "First choice admission aspiration."),
		"source": _ensure_lead_source("FPTU Open Day"),
		"admission_year": _ensure_admission_year(),
		"notes": (
			"Realistic FPTU sample: admitted Software Engineering student preparing "
			"for enrollment, with school records, language certificate, campaign, "
			"event, interactions, and intents."
		),
	})


def _update_contact_child_tables(contact):
	contact.set(
		"academic_results",
		[
			{
				"school_year": "2023-2024",
				"grade": "11",
				"academic_rank": "Giỏi",
				"gpa": 8.4,
			},
			{
				"school_year": "2024-2025",
				"grade": "12",
				"academic_rank": "Giỏi",
				"gpa": 8.8,
			},
		],
	)
	contact.set(
		"language_certificates",
		[
			{
				"language": "Tiếng Anh",
				"certificate_name": "IELTS",
				"score_level": "6.5",
				"issue_date": frappe.utils.add_months(frappe.utils.today(), -5),
				"expiry_date": frappe.utils.add_months(frappe.utils.today(), 19),
			}
		],
	)


def _ensure_contact(student):
	existing = frappe.db.exists("CRM Contact", {"student": student.name})
	if existing:
		contact = frappe.get_doc("CRM Contact", existing)
		_apply_contact_fields(contact, student)
		_update_contact_child_tables(contact)
		contact.save(ignore_permissions=True)
		return contact

	contact = frappe.get_doc({
		"doctype": "CRM Contact",
	})
	_apply_contact_fields(contact, student)
	_update_contact_child_tables(contact)
	contact.insert(ignore_permissions=True)

	student.db_set("converted", 1)
	return contact


def _apply_contact_fields(contact, student):
	contact.update({
		"full_name": student.student_name,
		"phone": student.mobile_no,
		"email": student.email,
		"stage": "Qualified",
		"lead_status": _ensure_lead_status("Promising"),
		"student": student.name,
		"high_school": student.high_school,
		"province": student.province,
		"major": student.major,
		"aspiration": student.aspiration,
		"source": student.source,
		"crm_campaign": _ensure_campaign(),
		"crm_event": _ensure_event(),
		"admission_year": student.admission_year,
		"branch": student.branch,
		"education_program": _ensure_education_program(),
		"cohort_start_year": datetime.now().year,
		"cohort_end_year": datetime.now().year + 4,
		"graduation_score": 8.6,
		"transcript_score": 8.8,
		"english_converted_score": 8.5,
		"total_score": 25.9,
		"admission_method": "Combined",
		"notes": (
			"FPTU HCMC prospective student has submitted application documents "
			"and is preparing for enrollment confirmation."
		),
	})


def _ensure_interactions(student, contact):
	interaction_specs = [
		{
			"type": "Form Submission",
			"description": "Student submitted an admission inquiry form.",
			"days_ago": 12,
			"outcome": "Captured",
			"summary": "FPTU 2026 admission inquiry form submitted",
			"notes": (
				"Student requested Software Engineering admission information, "
				"tuition estimate, and scholarship policy for FPTU HCMC."
			),
		},
		{
			"type": "Event Attendance",
			"description": "Student attended an admission event or campus visit.",
			"days_ago": 7,
			"outcome": "Captured",
			"summary": "Attended FPTU HCMC campus visit",
			"notes": (
				"Student joined the campus visit, met admissions counselor, "
				"and confirmed Software Engineering as first choice."
			),
		},
		{
			"type": "Application Submission",
			"description": "Student submitted admission application documents.",
			"days_ago": 2,
			"outcome": "Follow Up Needed",
			"summary": "Application documents submitted for FPTU enrollment",
			"notes": (
				"Application package received. Counselor needs to confirm tuition "
				"payment schedule and final enrollment checklist."
			),
		},
	]
	interaction_names = []
	for spec in interaction_specs:
		interaction_type = _ensure_interaction_type(spec["type"], spec["description"])
		existing = frappe.db.exists(
			"CRM Interaction",
			{
				"student": student.name,
				"interaction_type": interaction_type,
				"summary": spec["summary"],
			},
		)
		if existing:
			interaction_names.append(existing)
			continue

		interaction = frappe.get_doc({
			"doctype": "CRM Interaction",
			"student": student.name,
			"crm_contact": contact.name,
			"interaction_type": interaction_type,
			"interaction_datetime": datetime.now() - timedelta(days=spec["days_ago"]),
			"outcome": spec["outcome"],
			"summary": spec["summary"],
			"notes": spec["notes"],
		})
		interaction.insert(ignore_permissions=True)
		interaction_names.append(interaction.name)

	return interaction_names


def _ensure_intents(interactions):
	intent_specs_by_interaction = {
		0: [
			(
				"Major Inquiry",
				"High",
				"Hỏi thông tin về một ngành học.",
				88,
				"Student asked about Software Engineering curriculum and career outcomes.",
			),
			(
				"Tuition Inquiry",
				"Very High",
				"Hỏi về học phí, chính sách đóng phí hoặc chi phí học tập.",
				90,
				"Student asked about tuition, installment options, and enrollment fees.",
			),
			(
				"Scholarship Inquiry",
				"Very High",
				"Hỏi về học bổng, điều kiện và giá trị học bổng.",
				84,
				"Student asked whether IELTS and GPA qualify for scholarship review.",
			),
		],
		1: [
			(
				"Campus Visit Inquiry",
				"High",
				"Hỏi hoặc đăng ký tham quan cơ sở.",
				92,
				"Student attended FPTU HCMC campus visit and asked about facilities.",
			),
			(
				"Student Life Inquiry",
				"Medium",
				"Hỏi về đời sống sinh viên, hoạt động và môi trường học tập.",
				76,
				"Student asked about clubs, dormitory options, and orientation week.",
			),
		],
		2: [
			(
				"Application Submission",
				"Very High",
				"Nộp hoặc hỏi về việc nộp hồ sơ tuyển sinh.",
				95,
				"Student submitted application documents for enrollment review.",
			),
			(
				"Enrollment Inquiry",
				"Very High",
				"Hỏi về ghi danh, xác nhận nhập học hoặc trạng thái nhập học.",
				91,
				"Student asked about final enrollment confirmation and next steps.",
			),
		],
	}
	intent_names = []
	for index, interaction_name in enumerate(interactions):
		for intent_type, importance, description_vi, confidence, notes in intent_specs_by_interaction.get(index, []):
			intent_type_name = _ensure_intent_type(intent_type, importance, description_vi)
			existing = frappe.db.exists(
				"CRM Intent",
				{
					"interaction": interaction_name,
					"intent_type": intent_type_name,
				},
			)
			if existing:
				intent_names.append(existing)
				continue

			intent = frappe.get_doc({
				"doctype": "CRM Intent",
				"interaction": interaction_name,
				"intent_type": intent_type_name,
				"confidence": confidence,
				"notes": notes,
			})
			intent.insert(ignore_permissions=True)
			intent_names.append(intent.name)

	return intent_names


def _ensure_score_template():
	template_name = "FPTU Admission Scoring 2026"
	existing = frappe.db.get_value("CRM Score Template", {"template_name": template_name}, "name")
	if existing:
		return existing

	return frappe.get_doc({
		"doctype": "CRM Score Template",
		"template_name": template_name,
		"status": "Active",
		"start_time": datetime.now() - timedelta(days=30),
		"end_time": datetime.now() + timedelta(days=365),
		"fit_scoring": '{"academic_fit": 30, "major_fit": 20}',
		"engagement_scoring": '{"form_submission": 10, "campus_visit": 15, "application_submission": 20}',
		"intent_scoring": '{"tuition": 10, "scholarship": 10, "enrollment": 20}',
		"time_decay_scoring": '{"recent_activity_days": 14}',
		"negative_scoring": '{"no_response": -10, "wrong_target": -30}',
	}).insert(ignore_permissions=True).name


def _ensure_score_histories(student, score_template):
	score_specs = [
		{
			"days_ago": 12,
			"fit_score": 24,
			"engagement_score": 12,
			"intent_score": 16,
			"time_decay_score": 4,
			"negative_score": 0,
			"final_score": 56,
			"details": [
				("Fit", "fit.major", "Software Engineering fit", 14, "Student selected Software Engineering as first choice."),
				("Engagement", "engagement.form", "Admission form submitted", 12, "Student submitted the inquiry form."),
			],
		},
		{
			"days_ago": 7,
			"fit_score": 29,
			"engagement_score": 22,
			"intent_score": 21,
			"time_decay_score": 5,
			"negative_score": 0,
			"final_score": 77,
			"details": [
				("Engagement", "engagement.visit", "Campus visit attended", 15, "Student attended campus visit."),
				("Intent", "intent.scholarship", "Scholarship inquiry", 10, "Student asked about scholarship criteria."),
			],
		},
		{
			"days_ago": 2,
			"fit_score": 32,
			"engagement_score": 27,
			"intent_score": 28,
			"time_decay_score": 6,
			"negative_score": -2,
			"final_score": 91,
			"details": [
				("Intent", "intent.enrollment", "Enrollment next steps", 18, "Student asked about final enrollment confirmation."),
				("Negative", "negative.delay", "Pending payment confirmation", -2, "Tuition payment confirmation is pending."),
			],
		},
	]
	names = []
	for spec in score_specs:
		scoring_time = datetime.now() - timedelta(days=spec["days_ago"])
		existing = frappe.db.exists(
			"CRM Score History",
			{
				"student": student.name,
				"score_template": score_template,
				"final_score": spec["final_score"],
			},
		)
		if existing:
			names.append(existing)
			continue

		doc = frappe.get_doc({
			"doctype": "CRM Score History",
			"student": student.name,
			"score_template": score_template,
			"scoring_time": scoring_time,
			"fit_score": spec["fit_score"],
			"engagement_score": spec["engagement_score"],
			"intent_score": spec["intent_score"],
			"time_decay_score": spec["time_decay_score"],
			"negative_score": spec["negative_score"],
			"final_score": spec["final_score"],
			"details": [
				{
					"category": category,
					"rule_id": rule_id,
					"signal": signal,
					"score": score,
					"reason": reason,
				}
				for category, rule_id, signal, score, reason in spec["details"]
			],
		})
		doc.insert(ignore_permissions=True)
		names.append(doc.name)

	return names


def _ensure_admission_context():
	return {
		"province": _ensure_province(),
		"ward": _ensure_ward(),
		"campus": _ensure_default_campus(),
		"high_school": _ensure_high_school(),
		"major": _ensure_major(),
		"aspiration": _ensure_aspiration("NV1", "First choice admission aspiration."),
		"source": _ensure_lead_source("FPTU Open Day"),
		"campaign": _ensure_campaign(),
		"event": _ensure_event(),
		"admission_year": _ensure_admission_year(),
		"education_program": _ensure_education_program(),
	}


def _ensure_enrollment_status(status_name):
	if frappe.db.exists("CRM Enrollment Status", status_name):
		return status_name

	return frappe.get_doc({
		"doctype": "CRM Enrollment Status",
		"status_name": status_name,
	}).insert(ignore_permissions=True).name


def _ensure_lead_status(status_name):
	if frappe.db.exists("CRM Lead Status", status_name):
		return status_name

	return frappe.get_doc({
		"doctype": "CRM Lead Status",
		"status_name": status_name,
		"description": "Demo admission lead status.",
	}).insert(ignore_permissions=True).name


def _ensure_lead_source(source_name):
	if frappe.db.exists("CRM Lead Source", source_name):
		return source_name

	return frappe.get_doc({
		"doctype": "CRM Lead Source",
		"source_name": source_name,
	}).insert(ignore_permissions=True).name


def _ensure_admission_year():
	current_year = str(datetime.now().year)
	if frappe.db.exists("CRM Admission Year", current_year):
		return current_year

	return frappe.get_doc({
		"doctype": "CRM Admission Year",
		"year_name": current_year,
		"start_date": f"{current_year}-01-01",
		"end_date": f"{current_year}-12-31",
		"is_active": 1,
	}).insert(ignore_permissions=True).name


def _ensure_province():
	existing = frappe.db.get_value("CRM Province", {"province_code": SAMPLE_PROVINCE_CODE}, "name")
	if existing:
		return existing

	return frappe.get_doc({
		"doctype": "CRM Province",
		"province_code": SAMPLE_PROVINCE_CODE,
		"province_name": SAMPLE_PROVINCE_NAME,
		"city_type": "Centrally Controlled City",
	}).insert(ignore_permissions=True).name


def _ensure_ward():
	existing = frappe.db.get_value("CRM Ward", {"ward_code": SAMPLE_WARD_CODE}, "name")
	if existing:
		return existing

	return frappe.get_doc({
		"doctype": "CRM Ward",
		"ward_code": SAMPLE_WARD_CODE,
		"ward_name": SAMPLE_WARD_NAME,
		"province": _ensure_province(),
		"province_name": SAMPLE_PROVINCE_NAME,
		"ward_type": "Ward",
	}).insert(ignore_permissions=True).name


def _ensure_default_campus():
	if frappe.db.exists("CRM Campus", SAMPLE_CAMPUS):
		return SAMPLE_CAMPUS

	return frappe.get_doc({
		"doctype": "CRM Campus",
		"campus_name": SAMPLE_CAMPUS,
		"campus_code": "FPTU-HCM",
		"is_default": 1,
		"province": _ensure_province(),
		"address": "Saigon Hi-Tech Park, Thu Duc City, Ho Chi Minh City",
		"phone": "+84 28 7300 5588",
	}).insert(ignore_permissions=True).name


def _ensure_major():
	if frappe.db.exists("CRM Major", SAMPLE_MAJOR):
		return SAMPLE_MAJOR

	return frappe.get_doc({
		"doctype": "CRM Major",
		"major_name": SAMPLE_MAJOR,
		"major_code": SAMPLE_MAJOR_CODE,
		"is_active": 1,
	}).insert(ignore_permissions=True).name


def _ensure_high_school():
	existing = frappe.db.exists(
		"CRM High School",
		{
			"school_name": SAMPLE_HIGH_SCHOOL,
			"province_code": SAMPLE_PROVINCE_CODE,
		},
	)
	if existing:
		return existing

	return frappe.get_doc({
		"doctype": "CRM High School",
		"school_name": SAMPLE_HIGH_SCHOOL,
		"school_code": "HCM-TDN",
		"ward_code": SAMPLE_WARD_CODE,
		"ward_name": SAMPLE_WARD_NAME,
		"province_code": SAMPLE_PROVINCE_CODE,
		"province_name": SAMPLE_PROVINCE_NAME,
		"address": "20 Ly Tu Trong, District 1, Ho Chi Minh City",
		"phone": "+84 28 3822 9088",
		"email": "admissions.demo@tdn.edu.vn",
	}).insert(ignore_permissions=True).name


def _ensure_aspiration(aspiration_name, description):
	if frappe.db.exists("CRM Aspiration", aspiration_name):
		return aspiration_name

	return frappe.get_doc({
		"doctype": "CRM Aspiration",
		"aspiration_name": aspiration_name,
		"description": description,
	}).insert(ignore_permissions=True).name


def _ensure_education_program():
	program_name = "FPTU Software Engineering 2026"
	if frappe.db.exists("CRM Education Program", program_name):
		return program_name

	return frappe.get_doc({
		"doctype": "CRM Education Program",
		"program_name": program_name,
		"program_type": "Chính quy",
	}).insert(ignore_permissions=True).name


def _ensure_campaign():
	if frappe.db.exists("CRM Campaign", SAMPLE_CAMPAIGN):
		return SAMPLE_CAMPAIGN

	return frappe.get_doc({
		"doctype": "CRM Campaign",
		"title": SAMPLE_CAMPAIGN,
		"campus": _ensure_default_campus(),
		"campaign_type": _ensure_campaign_type("Open Day", "Campus visit and admission counseling campaign."),
		"start_date": f"{datetime.now().year}-01-01",
		"end_date": f"{datetime.now().year}-12-31",
		"budget": 250000000,
		"notes": "Demo FPTU HCMC admission campaign for students preparing to enroll.",
	}).insert(ignore_permissions=True).name


def _ensure_campaign_type(campaign_type_name, description):
	if frappe.db.exists("CRM Campaign Type", campaign_type_name):
		return campaign_type_name

	return frappe.get_doc({
		"doctype": "CRM Campaign Type",
		"campaign_type_name": campaign_type_name,
		"description": description,
	}).insert(ignore_permissions=True).name


def _ensure_event():
	if frappe.db.exists("CRM Event", SAMPLE_EVENT):
		return SAMPLE_EVENT

	return frappe.get_doc({
		"doctype": "CRM Event",
		"title": SAMPLE_EVENT,
		"crm_campaign": _ensure_campaign(),
		"province": _ensure_province(),
		"event_date": frappe.utils.add_days(frappe.utils.today(), -7),
		"location": SAMPLE_CAMPUS,
		"notes": "Campus visit for admitted and near-enrollment FPTU students.",
	}).insert(ignore_permissions=True).name


def _ensure_interaction_type(interaction_type_name, description):
	if frappe.db.exists("CRM Interaction Type", interaction_type_name):
		return interaction_type_name

	return frappe.get_doc({
		"doctype": "CRM Interaction Type",
		"interaction_type_name": interaction_type_name,
		"description": description,
	}).insert(ignore_permissions=True).name


def _ensure_intent_type(intent_type_name, importance, description_vi):
	if frappe.db.exists("CRM Intent Type", intent_type_name):
		return intent_type_name

	return frappe.get_doc({
		"doctype": "CRM Intent Type",
		"intent_type_name": intent_type_name,
		"importance": importance,
		"description_vi": description_vi,
	}).insert(ignore_permissions=True).name
