"""Seed one complete Student 360 fixture for the local admissions API.

Run with::

    bench --site crm.localhost execute crm.demo.seed_student_detail.execute

The fixture is intentionally separate from the large showcase cohort.  It uses
stable source/idempotency keys and the same service commands as production API
flows, so re-running it is safe and useful for local API development.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import frappe

from crm.demo import seed_demo, seed_staff

LOCAL_SITE = "crm.localhost"
NAMESPACE = "crm-demo-student-detail"
STUDENT_EMAIL = "minh.anh.student360@example.test"
STUDENT_PHONE = "0901999123"
PARENT_EMAIL = "thu.ha.parent360@example.test"
PARENT_PHONE = "0908999765"
SEED_NOW = datetime(2026, 9, 1, 10, 0, 0)


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) == LOCAL_SITE or frappe.conf.get("allow_demo_seed"):
		return
	frappe.throw(
		"The Student detail seed only runs on crm.localhost. Set allow_demo_seed=1 "
		"to opt in a demo/staging site.",
		frappe.PermissionError,
	)


@contextmanager
def _seed_flags():
	keys = {
		"crm_student_routing_enabled": 1,
		"crm_student_context_read_enabled": 1,
		"crm_student_engagement_write_enabled": 1,
		"crm_student_lifecycle_write_enabled": 1,
		"crm_student_conversion_read_enabled": 1,
		"crm_student_conversion_write_enabled": 1,
		"crm_phase9_governance_write_enabled": 1,
		"crm_phase9_audit_read_enabled": 1,
	}
	previous_config = {key: frappe.conf.get(key) for key in keys}
	previous_flags = {
		"crm_governance_additive": frappe.flags.get("crm_governance_additive"),
		"crm_governance_change": frappe.flags.get("crm_governance_change"),
		"legacy_fact_migration": frappe.flags.get("legacy_fact_migration"),
	}
	try:
		for key, value in keys.items():
			frappe.conf[key] = value
		frappe.flags.crm_governance_additive = True
		frappe.flags.crm_governance_change = True
		frappe.flags.legacy_fact_migration = True
		yield
	finally:
		for key, value in previous_flags.items():
			if value is None:
				frappe.flags.pop(key, None)
			else:
				frappe.flags[key] = value
		for key, value in previous_config.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value


def _key(*parts: Any) -> str:
	return ":".join((NAMESPACE, *(str(part) for part in parts)))


def _ensure_interaction_type(name: str) -> str:
	term = frappe.db.get_value("CRM Term", {"term_name": name, "category": "interaction_type"}, "name")
	if term:
		return term
	return (
		frappe.get_doc({"doctype": "CRM Term", "term_name": name, "category": "interaction_type"})
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_intent_type(name: str, importance: str) -> str:
	term = frappe.db.get_value("CRM Term", {"term_name": name, "category": "intent_type"}, "name")
	if term:
		return term
	return seed_demo._ensure_intent_type(name, importance, f"Student detail fixture: {name}")


def _submit_student(context: dict[str, Any], pool: str) -> str:
	from crm.fcrm.student_intake import submit_intake

	payload = {
		"student_name": "Nguyễn Minh Anh",
		"email": STUDENT_EMAIL,
		"phone": STUDENT_PHONE,
		"id_number": "079208012345",
		"gender": "Nữ",
		"date_of_birth": "2008-04-15",
		"admission_method": "Transcript Review",
		"campus": context["campus"],
		"owning_team": pool,
		"admission_year": context["admission_year"],
		"enrollment_status": context["enrollment_status"],
		"high_school": context["high_school"],
		"province": context["province"],
		"ward": context["ward"],
		"current_grade": "12",
		"study_stage": "grade_12_h2",
		"major": context["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"advertising_channel": "Facebook Ads - Scholarship 2026",
		"alt_name": "Trần Thị Thu Hà",
		"alt_phone": PARENT_PHONE,
		"consent": {
			"granted": True,
			"granted_at": str(SEED_NOW - timedelta(days=9)),
			"purpose": "admissions_counseling",
			"scope": "student_profile_and_parent_follow_up",
			"source": NAMESPACE,
		},
	}
	existing = frappe.db.get_value("CRM Student", {"email": STUDENT_EMAIL}, "name")
	if existing:
		if not frappe.db.exists("CRM Contact Consent Event", {"student": existing, "event_type": "Granted"}):
			submit_intake(
				payload,
				source_namespace=NAMESPACE,
				source_record_id="student:consent-repair",
				idempotency_key=_key("intake", "consent-repair"),
				correlation_id=_key("student", "consent-repair"),
			)
		return existing

	result = submit_intake(
		payload,
		source_namespace=NAMESPACE,
		source_record_id="student:minh-anh",
		idempotency_key=_key("intake", "student:minh-anh"),
		correlation_id=_key("student", "minh-anh"),
	)
	if result.get("outcome") not in {"created", "attached"} or not result.get("student"):
		frappe.throw(f"Student intake did not resolve: {result}", frappe.ValidationError)
	return result["student"]


def _complete_student_profile(student: str, context: dict[str, Any]) -> None:
	doc = frappe.get_doc("CRM Student", student)
	values = {
		"admission_method": "Transcript Review",
		"branch": context["campus"],
		"major": context["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"advertising_channel": "Facebook Ads - Scholarship 2026",
		"admission_year": context["admission_year"],
		"cohort_start_year": 2023,
		"cohort_end_year": 2026,
		"education_program": context["education_program"],
		"graduation_score": 8.8,
		"transcript_score": 8.9,
		"english_converted_score": 7.5,
		"total_score": 25.2,
		"step": 3,
		"alt_name": "Trần Thị Thu Hà",
		"alt_phone": PARENT_PHONE,
		"alt_address": "Quận Bình Thạnh, Thành phố Hồ Chí Minh",
		"id_number": "079208012345",
		"id_issued_date": "2024-05-18",
		"id_issued_place": "Cục Cảnh sát QLHC về TTXH",
		"import_source_id": f"{NAMESPACE}:student:minh-anh",
		"notes": "Demo Student 360 đầy đủ cho kiểm thử API detail và admissions workspace.",
	}
	changed = False
	for field, value in values.items():
		if doc.get(field) != value:
			doc.set(field, value)
			changed = True
	if not any(row.school_year == "2025-2026" for row in doc.get("academic_results")):
		doc.append(
			"academic_results",
			{"school_year": "2025-2026", "grade": "12", "academic_rank": "Giỏi", "gpa": 8.9},
		)
		changed = True
	if not any(row.school_year == "2024-2025" for row in doc.get("academic_results")):
		doc.append(
			"academic_results",
			{"school_year": "2024-2025", "grade": "11", "academic_rank": "Giỏi", "gpa": 8.7},
		)
		changed = True
	if not any(row.certificate_name == "IELTS Academic" for row in doc.get("language_certificates")):
		doc.append(
			"language_certificates",
			{
				"language": "Tiếng Anh",
				"certificate_name": "IELTS Academic",
				"score_level": "7.5",
				"issue_date": "2025-08-20",
				"expiry_date": "2027-08-20",
			},
		)
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _ensure_interaction(
	student: str,
	key: str,
	interaction_type: str,
	when: datetime,
	channel: str,
	direction: str,
	summary: str,
) -> str:
	external_id = _key("interaction", key)
	existing = frappe.db.get_value("CRM Interaction", {"external_id": external_id}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"student": student,
				"interaction_type": _ensure_interaction_type(interaction_type),
				"interaction_datetime": when,
				"external_id": external_id,
				"source_namespace": NAMESPACE,
				"source_record_id": key,
				"channel": channel,
				"direction": direction,
				"actor": "nguyen.minh.khoi@gmail.com",
				"summary": summary,
				"notes": "Nguồn dữ liệu demo, không gửi thông báo ra ngoài.",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_intent(student: str, interaction: str, intent_type: str, role: str, confidence: int) -> str:
	intent = _ensure_intent_type(
		intent_type, "High" if intent_type in {"Scholarship", "Tuition"} else "Medium"
	)
	existing = frappe.db.get_value(
		"CRM Intent", {"interaction": interaction, "intent_type": intent, "intent_role": role}, "name"
	)
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Intent",
				"interaction": interaction,
				"student": student,
				"intent_type": intent,
				"intent_role": role,
				"polarity": "Positive",
				"confidence": confidence,
				"notes": "Học sinh chủ động hỏi và xác nhận nhu cầu trong buổi tư vấn.",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_outcome(student: str, interaction: str, evidence_file: str) -> str:
	from crm.fcrm.student_engagement import record_outcome

	source_key = _key("outcome", "qualified")
	existing = frappe.db.get_value("CRM Student Outcome", {"source_key": source_key}, "name")
	if existing:
		return existing
	result = record_outcome(
		student=student,
		interaction=interaction,
		outcome_code="qualified",
		continuity_kind="task",
		next_action={"title": "Gọi phụ huynh xác nhận điều kiện học bổng và hồ sơ"},
		next_action_assignee="nguyen.minh.khoi@gmail.com",
		next_action_due_at=SEED_NOW + timedelta(days=1),
		qualification_evidence=[{"category": "document", "doctype": "File", "name": evidence_file}],
		source_key=source_key,
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key=_key("outcome", "qualified"),
		correlation_id=_key("student", "minh-anh"),
	)
	return result["event"]


def _ensure_file(student: str) -> str:
	file_name = f"{NAMESPACE}-phieu-tiep-nhan-ho-so.txt"
	existing = frappe.db.get_value(
		"File",
		{"attached_to_doctype": "CRM Student", "attached_to_name": student, "file_name": file_name},
		"name",
	)
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"is_private": 1,
				"content": "Phiếu tiếp nhận hồ sơ tuyển sinh demo\\nHọc sinh: Nguyễn Minh Anh\\n",
				"attached_to_doctype": "CRM Student",
				"attached_to_name": student,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_lifecycle(student: str, outcome: str, intent: str, evidence_file: str) -> None:
	from crm.fcrm.student_lifecycle import request_transition

	for target, evidence in (
		(
			"MQL",
			[
				{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
				{"category": "intent", "doctype": "CRM Intent", "name": intent},
			],
		),
		(
			"Applicant",
			[
				{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
				{"category": "document", "doctype": "File", "name": evidence_file},
			],
		),
	):
		doc = frappe.get_doc("CRM Student", student)
		if doc.lifecycle_stage == target:
			continue
		if doc.lifecycle_stage not in {"Lead", "MQL"}:
			if doc.lifecycle_stage == "Applicant" and target == "MQL":
				continue
			frappe.throw(
				f"Unexpected lifecycle stage {doc.lifecycle_stage} before {target}.", frappe.ValidationError
			)
		if target == "MQL" and doc.lifecycle_stage != "Lead":
			continue
		if target == "Applicant" and doc.lifecycle_stage != "MQL":
			continue
		request_transition(
			student,
			target,
			reason=f"Đủ bằng chứng nghiệp vụ để chuyển sang {target} trong fixture Student 360.",
			evidence_refs=evidence,
			outcome_code="qualified",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_key("lifecycle", target),
			correlation_id=_key("student", "minh-anh"),
		)


def _ensure_parent(student: str, context: dict[str, Any], team: str) -> dict[str, str]:
	from crm.fcrm.student_parent_context import record_parent_contact_authority

	contact = frappe.db.get_value("CRM Contact", {"email": PARENT_EMAIL}, "name")
	if not contact:
		previous = frappe.flags.get("student_conversion_service")
		frappe.flags.student_conversion_service = True
		try:
			contact = (
				frappe.get_doc(
					{
						"doctype": "CRM Contact",
						"full_name": "Trần Thị Thu Hà",
						"phone": PARENT_PHONE,
						"email": PARENT_EMAIL,
						"enrollment_status": context["enrollment_status"],
						"lead_status": "Mới",
						"readiness_level": "Level 2 - Đang so sánh",
						"quality_bucket": "Warm",
						"is_verified_lead": 1,
						"decision_maker": "Parent",
						"preferred_contact_channel": "Phone",
						"owning_team": team,
						"branch": context["campus"],
						"major": context["major"],
						"high_school": context["high_school"],
						"province": context["province"],
						"source": context["source"],
						"admission_year": context["admission_year"],
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		finally:
			frappe.flags.student_conversion_service = previous
	authority = frappe.db.get_value(
		"CRM Parent Contact Authority", {"student": student, "contact": contact}, "name"
	)
	if not authority:
		authority = record_parent_contact_authority(
			student,
			contact,
			relationship_type="Mẹ",
			decision_role="Primary decision maker",
			decision_influence="High",
			concerns="Quan tâm học phí, học bổng và thời hạn hoàn tất hồ sơ.",
			lawful_basis="consent",
			allowed_channels=["Phone", "Email", "Zalo"],
			proof_reference=f"{NAMESPACE}:parent-consent",
			effective_at=SEED_NOW - timedelta(days=8),
		)
		authority = authority["name"]
	guardian = frappe.db.get_value("CRM Student Guardian", {"student": student, "contact": contact}, "name")
	if not guardian:
		guardian = (
			frappe.get_doc(
				{
					"doctype": "CRM Student Guardian",
					"student": student,
					"contact": contact,
					"relationship": "Parent",
					"decision_role": "Decision Maker",
					"involvement": "Primary",
					"preferred_channel": "Phone",
					"best_contact_time": "18:00-20:00",
					"consent_summary": "Đã xác nhận là đầu mối phụ huynh cho tư vấn tuyển sinh.",
					"consent_evidence": {"source": NAMESPACE, "authority": authority},
					"is_active": 1,
					"source_reference": _key("parent", "guardian"),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return {"contact": contact, "authority": authority, "guardian": guardian}


def _ensure_attribution(student: str, context: dict[str, Any]) -> dict[str, Any]:
	from crm.fcrm.student_attribution import record_campaign_touchpoint, record_event_participation

	campaign_key = _key("campaign", "open-day")
	if not frappe.db.exists("CRM Marketing Engagement", {"idempotency_key": campaign_key}):
		record_campaign_touchpoint(
			student,
			context["campaign"],
			touched_at=SEED_NOW - timedelta(days=7),
			source="Manual",
			notes="Đăng ký từ landing page học bổng và ngày hội Open Day.",
			idempotency_key=campaign_key,
			correlation_id=_key("attribution", "open-day"),
		)
	event_key = _key("event", "campus-visit")
	if not frappe.db.exists("CRM Marketing Engagement", {"idempotency_key": event_key}):
		record_event_participation(
			student,
			context["event"],
			status="Checked-in",
			registered_at=SEED_NOW - timedelta(days=5),
			checked_in_at=SEED_NOW - timedelta(days=5, hours=-1),
			feedback_rating=5,
			feedback_notes="Đã tham quan campus và trao đổi với chuyên viên tuyển sinh.",
			idempotency_key=event_key,
			correlation_id=_key("attribution", "campus-visit"),
		)
	return {"campaign": context["campaign"], "event": context["event"]}


def _ensure_assessment(student: str, interaction: str, intent: str, application: str | None) -> str:
	from crm.fcrm.student_assessment import record_student_assessment

	existing = frappe.db.get_value(
		"CRM Student Assessment", {"student": student, "status": "confirmed"}, "name"
	)
	if existing:
		return existing
	evidence = [f"CRM Interaction:{interaction}", f"CRM Intent:{intent}"]
	if application:
		evidence.append(f"CRM Admission Application:{application}")
	result = record_student_assessment(
		student,
		{
			"interest": "High",
			"interest_confidence": 91,
			"fit": "High",
			"fit_confidence": 86,
			"primary_barrier": "Cost",
			"barrier_confidence": 74,
			"enrollment_probability": 78,
		},
		source="manual",
		reason="Học sinh có GPA tốt, IELTS 7.5, đã tham dự campus visit và chủ động hỏi về học bổng; rào cản chính là ngân sách gia đình.",
		evidence_references=evidence,
		model_version="student-detail-demo-2026.09",
		confirm=True,
	)
	return result["name"]


def _ensure_action(student: str, owner_staff: str) -> str:
	from crm.fcrm.student_decision import _command_key, create_manual_action

	idempotency_key = _key("action", "parent-scholarship-call")
	command_key = _command_key("manual_action", "Administrator", idempotency_key)
	existing = frappe.db.get_value("CRM Action", {"generation_idempotency_key": command_key}, "name")
	if existing:
		return existing
	return create_manual_action(
		student,
		"PARENT_CONTACT",
		"Gọi phụ huynh xác nhận điều kiện học bổng và hồ sơ còn thiếu",
		idempotency_key=idempotency_key,
		due_at=SEED_NOW + timedelta(days=1),
		priority="high",
		assignee_staff=owner_staff,
	)["action"]


def _ensure_application(student: str, context: dict[str, Any]) -> str:
	from crm.demo import seed_admission_funnel
	from crm.fcrm.admission_application import create_application

	method = "Transcript Review"
	offering = frappe.db.get_value(
		"CRM Admission Offering",
		{
			"admission_year": context["admission_year"],
			"campus": context["campus"],
			"major": context["major"],
			"admission_method": method,
			"status": "Active",
		},
		"name",
	)
	if not offering:
		offering, _ = seed_admission_funnel._ensure_offering(
			{"branch": context["campus"], "major": context["major"], "admission_method": method},
			context,
		)
	source_reference = _key("application", "transcript-review")
	existing = frappe.db.get_value(
		"CRM Admission Application", {"source_reference": source_reference}, "name"
	)
	if existing:
		return existing
	result = create_application(
		student=student,
		values={
			"offering": offering,
			"status": "Under Review",
			"preference_order": 1,
			"preference": "Primary",
			"document_total": 8,
			"document_completed": 6,
			"scholarship_percentage": 25,
			"deadline": "2026-09-30",
			"submitted_at": SEED_NOW - timedelta(days=2),
			"source_reference": source_reference,
		},
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key=_key("application", "transcript-review"),
	)
	return result["application"]


def _ensure_score(student: str) -> str:
	from crm.api.scoring_write import append_local_fixture_score
	from crm.fcrm.scoring_policy import get_active_policy

	existing = frappe.db.get_value(
		"CRM Score History", {"student": student}, "name", order_by="creation desc"
	)
	if existing:
		return existing
	policy = get_active_policy()
	if not policy:
		frappe.throw("No active CRM scoring policy is available.", frappe.ValidationError)
	doc = frappe.get_doc("CRM Student", student)
	result = append_local_fixture_score(
		student=student,
		source_score_input_revision=int(doc.score_input_revision or 0),
		policy_revision=policy["policy_revision"],
		policy_hash=policy["policy_hash"],
		score_template=policy["template_id"],
		scoring_time=str(SEED_NOW),
		fit_score=34,
		engagement_score=27,
		intent_score=30,
		time_decay_score=0,
		negative_score=-4,
		final_score=87,
		score_change=87 - float(doc.latest_score or 0),
		details=[
			{"category": "Fit", "signal": "Grade 12 + academic results", "score": 34},
			{"category": "Engagement", "signal": "Campus visit + counseling", "score": 27},
			{"category": "Intent", "signal": "Scholarship and major inquiry", "score": 30},
			{"category": "Negative", "signal": "Budget concern", "score": -4},
		],
	)
	return result.get("history") or ""


def execute() -> dict[str, Any]:
	_assert_local_site()
	frappe.set_user("Administrator")
	from crm.demo import seed_showcase

	seed_showcase.ensure_local_integrity_keys()
	seed_showcase.ensure_demo_config()
	with _seed_flags():
		context = seed_demo._bootstrap()
		staff_context = seed_staff._bootstrap()
		seed_showcase._ensure_lifecycle_statuses()
		seed_showcase._ensure_policies(staff_context["campus"], staff_context["pool"])
		frappe.db.commit()

		student = _submit_student(context, staff_context["pool"])
		_complete_student_profile(student, context)
		owner_staff = frappe.db.get_value("CRM Student", student, "owner_staff")
		if not owner_staff:
			owner_staff = seed_showcase._ensure_assigned(student)
		frappe.db.commit()

		_ensure_interaction(
			student,
			"website-form",
			"Website Visit",
			SEED_NOW - timedelta(days=8),
			"Website form",
			"inbound",
			"Đăng ký nhận thông tin ngành Software Engineering và học bổng.",
		)
		interaction_counseling = _ensure_interaction(
			student,
			"initial-counseling",
			"Counseling",
			SEED_NOW - timedelta(days=6),
			"Phone",
			"outbound",
			"Tư vấn lộ trình xét học bạ, học phí và điều kiện học bổng.",
		)
		interaction_latest = _ensure_interaction(
			student,
			"campus-follow-up",
			"Connected",
			SEED_NOW - timedelta(days=2),
			"Phone",
			"inbound",
			"Học sinh xác nhận muốn nộp hồ sơ và cần gọi phụ huynh chốt ngân sách.",
		)
		intent_major = _ensure_intent(student, interaction_counseling, "Major Inquiry", "Support", 89)
		intent_scholarship = _ensure_intent(student, interaction_latest, "Scholarship", "Dominant", 96)
		intent_tuition = _ensure_intent(student, interaction_latest, "Tuition", "Support", 88)
		evidence_file = _ensure_file(student)
		outcome = _ensure_outcome(student, interaction_latest, evidence_file)
		_ensure_lifecycle(student, outcome, intent_scholarship, evidence_file)
		application = _ensure_application(student, context)
		parent = _ensure_parent(student, context, staff_context["team"])
		attribution = _ensure_attribution(student, context)
		assessment = _ensure_assessment(student, interaction_latest, intent_scholarship, application)
		action = _ensure_action(student, owner_staff)
		score = _ensure_score(student)
		frappe.db.commit()

		counts = {
			"interactions": frappe.db.count("CRM Interaction", {"student": student}),
			"intents": frappe.db.count("CRM Intent", {"student": student}),
			"outcomes": frappe.db.count("CRM Student Outcome", {"student": student}),
			"lifecycle_events": frappe.db.count("CRM Student Lifecycle Event", {"student": student}),
			"assessments": frappe.db.count("CRM Student Assessment", {"student": student}),
			"parent_authorities": frappe.db.count("CRM Parent Contact Authority", {"student": student}),
			"consent_events": frappe.db.count("CRM Contact Consent Event", {"student": student}),
			"geography_snapshots": frappe.db.count("CRM Student Geography Snapshot", {"student": student}),
			"applications": frappe.db.count("CRM Admission Application", {"student": student}),
			"actions": frappe.db.count("CRM Action", {"student": student}),
			"scores": frappe.db.count("CRM Score History", {"student": student}),
		}
		result = {
			"student": student,
			"student_name": frappe.db.get_value("CRM Student", student, "student_name"),
			"lifecycle_stage": frappe.db.get_value("CRM Student", student, "lifecycle_stage"),
			"owner_staff": owner_staff,
			"application": application,
			"parent": parent,
			"assessment": assessment,
			"action": action,
			"score_history": score,
			"attribution": attribution,
			"intent_ids": {
				"major": intent_major,
				"scholarship": intent_scholarship,
				"tuition": intent_tuition,
			},
			"outcome": outcome,
			"counts": counts,
		}
	print(frappe.as_json(result))
	return result


def verify() -> dict[str, Any]:
	student = frappe.db.get_value("CRM Student", {"email": STUDENT_EMAIL}, "name")
	if not student:
		frappe.throw("Student detail fixture has not been seeded.", frappe.DoesNotExistError)
	from crm.api.student_context import get_student_context

	context = get_student_context(student, history_limit=50)
	result = {
		"student": student,
		"student_name": context["student"]["student_name"],
		"stage": context["lifecycle"]["stage"],
		"latest_interaction": bool(context["latest_interaction"]),
		"latest_outcome": bool(context["latest_outcome"]),
		"next_action": bool(context["next_action"]),
		"assessment": bool(context["assessment"].get("current")),
		"parent_context": len(context["parent_context"]),
		"privacy_status": context["privacy"].get("status"),
		"campaign": bool(context["admissions_context"].get("campaign")),
		"event": bool(context["admissions_context"].get("event")),
		"scholarship": bool(context["admissions_context"].get("scholarship")),
		"score_state": context["admissions_context"]["score"].get("state"),
		"history_count": len(context["history"]),
		"active_actions": [
			{
				"name": row.name,
				"generation_idempotency_key": row.generation_idempotency_key,
				"due_at": row.due_at,
			}
			for row in frappe.get_all(
				"CRM Action",
				filters={
					"student": student,
					"state": ["in", ["pending", "accepted", "in-progress", "requires-review", "deferred"]],
				},
				fields=["name", "generation_idempotency_key", "due_at"],
				order_by="due_at asc, name asc",
			)
		],
	}
	print(frappe.as_json(result))
	return result
