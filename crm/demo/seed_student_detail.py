"""Seed one complete, local-only Student 360 fixture for the Director dashboard.

Run with::

    bench --site crm.localhost execute crm.demo.seed_student_detail.seed

The fixture is intentionally limited to Website, Event, Form, and Email data.
It does not create calls, Zalo records, or tasks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe

LOCAL_SITE = "crm.localhost"
STUDENT_ID = "ENR-2026-04561"
STUDENT_NAME = "Lê Gia Uyên"
STUDENT_EMAIL = "le.gia.uyen@gmail.com"
SEED_NAMESPACE = "crm-demo-student-detail:gia-uyen"
SEED_NOW = datetime(2026, 9, 3, 16, 11, 5)

REFERENCE_DOCTYPES = {
	"high_school": "CRM High School",
	"province": "CRM Province",
	"major": "CRM Major",
	"source": "CRM Lead Source",
	"admission_year": "CRM Admission Year",
}

INTERACTIONS: tuple[dict[str, Any], ...] = (
	{
		"key": "major-page",
		"when": datetime(2026, 8, 18, 9, 10),
		"channel": "Website",
		"direction": "inbound",
		"summary": "Xem trang ngành Trí tuệ nhân tạo",
		"notes": "Đọc thông tin chương trình và đầu ra ngành AI.",
		"outcome": "Captured",
	},
	{
		"key": "event-registration",
		"when": datetime(2026, 8, 21, 18, 20),
		"channel": "Sự kiện",
		"direction": "inbound",
		"summary": "Đăng ký ngày hội AI",
		"notes": "Đăng ký tham dự buổi tư vấn ngành và học bổng.",
		"outcome": "Captured",
	},
	{
		"key": "consultation-form",
		"when": datetime(2026, 8, 24, 10, 5),
		"channel": "Hồ sơ",
		"direction": "inbound",
		"summary": "Hoàn tất biểu mẫu tư vấn",
		"notes": "Cung cấp nguyện vọng Artificial Intelligence và thông tin học tập.",
		"outcome": "Resolved",
	},
	{
		"key": "tuition-page",
		"when": datetime(2026, 8, 27, 20, 15),
		"channel": "Website",
		"direction": "inbound",
		"summary": "Xem học phí và học bổng",
		"notes": "Quan tâm mức học phí, học bổng và lộ trình xét tuyển.",
		"outcome": "Follow Up Needed",
	},
	{
		"key": "event-attendance",
		"when": datetime(2026, 8, 30, 8, 40),
		"channel": "Sự kiện",
		"direction": "inbound",
		"summary": "Tham gia ngày hội tư vấn AI",
		"notes": "Đã tham dự và trao đổi về chương trình đào tạo.",
		"outcome": "Captured",
	},
	{
		"key": "need-confirmed",
		"when": SEED_NOW,
		"channel": "Website",
		"direction": "inbound",
		"summary": "Xác nhận nhu cầu ngành AI",
		"notes": "Nhu cầu ngành học đã rõ, cần tiếp tục hoàn thiện hồ sơ.",
		"outcome": "Follow Up Needed",
		"next_follow_up_action": "Gửi checklist hồ sơ và thông tin học bổng.",
	},
)

ASSESSMENTS: tuple[dict[str, Any], ...] = (
	{
		"key": "initial",
		"when": datetime(2026, 8, 18, 9, 20),
		"probability": 42,
		"signal_score": 48,
		"interest": "Medium",
		"fit": "Medium",
		"barrier": "Information",
		"reason": "Học sinh mới để lại thông tin và cần thêm tư vấn về ngành học.",
		"recommendation": "Gửi thông tin tổng quan về ngành Artificial Intelligence.",
	},
	{
		"key": "event-interest",
		"when": datetime(2026, 8, 21, 18, 30),
		"probability": 55,
		"signal_score": 62,
		"interest": "Medium",
		"fit": "High",
		"barrier": "Information",
		"reason": "Đăng ký ngày hội và thể hiện mức quan tâm rõ hơn tới ngành AI.",
		"recommendation": "Mời tham gia buổi tư vấn chuyên sâu về ngành.",
	},
	{
		"key": "form-completed",
		"when": datetime(2026, 8, 24, 10, 15),
		"probability": 64,
		"signal_score": 72,
		"interest": "High",
		"fit": "High",
		"barrier": "Information",
		"reason": "Đã hoàn tất biểu mẫu và cung cấp nguyện vọng cụ thể.",
		"recommendation": "Đối chiếu hồ sơ học tập và phương thức xét tuyển.",
	},
	{
		"key": "tuition-concern",
		"when": datetime(2026, 8, 27, 20, 25),
		"probability": 76,
		"signal_score": 82,
		"interest": "High",
		"fit": "High",
		"barrier": "Cost",
		"reason": "Tương tác lặp lại với nội dung học phí và học bổng cho thấy ý định cao.",
		"recommendation": "Chuẩn bị phương án học phí và học bổng phù hợp.",
	},
	{
		"key": "current",
		"when": datetime(2026, 9, 3, 16, 20),
		"probability": 90,
		"signal_score": 90,
		"interest": "High",
		"fit": "High",
		"barrier": "Cost",
		"reason": "Học sinh đã xác nhận ngành quan tâm; rào cản còn lại là phương án tài chính.",
		"recommendation": "Gửi checklist hồ sơ cùng phương án học bổng trong ngày.",
	},
)


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) == LOCAL_SITE or frappe.conf.get("allow_demo_seed"):
		return
	frappe.throw(
		"seed_student_detail chỉ chạy trên crm.localhost. Có thể bật allow_demo_seed=1 cho site demo.",
		frappe.PermissionError,
	)


def _ensure_interaction_type(name: str) -> str:
	from crm.demo import seed_demo

	return seed_demo._ensure_interaction_type(name)


def _resolve_student() -> str:
	student = frappe.db.exists("CRM Student", STUDENT_ID)
	if student:
		return student
	student = frappe.db.get_value("CRM Student", {"email": STUDENT_EMAIL}, "name")
	if student:
		return student
	student = frappe.db.get_value("CRM Student", {"student_name": STUDENT_NAME}, "name")
	if student:
		return student

	doc = frappe.get_doc(
		{
			"doctype": "CRM Student",
			"student_name": STUDENT_NAME,
			"phone": "0908000176",
			"email": STUDENT_EMAIL,
			"gender": "Nữ",
			"date_of_birth": "2009-04-16",
		}
	).insert(ignore_permissions=True)
	return doc.name


def _set_student_profile(student: str) -> None:
	doc = frappe.get_doc("CRM Student", student)
	values: dict[str, Any] = {
		"student_name": STUDENT_NAME,
		"phone": "0908000176",
		"email": STUDENT_EMAIL,
		"gender": "Nữ",
		"date_of_birth": "2009-04-16",
		"current_grade": "10",
		"study_stage": "grade_10",
		"graduation_score": 8.6,
		"transcript_score": 8.8,
		"english_converted_score": 7.0,
		"total_score": 24.4,
		"step": 3,
		"alt_name": "Nguyễn Thị Hương",
		"alt_phone": "0908000177",
		"alt_address": "Thành phố Cao Lãnh, Đồng Tháp",
		"advertising_channel": "Website tuyển sinh",
		"notes": "Hồ sơ demo đầy đủ cho màn hình Director Student 360.",
		"id_number": "082309041612",
		"id_issued_date": "2025-05-20",
		"id_issued_place": "Cục Cảnh sát QLHC về TTXH",
		"import_source_id": f"{SEED_NAMESPACE}:student",
	}
	for field, value in {
		"high_school": "THPT Rạch Gầm-Xoài Mút",
		"province": "Đồng Tháp",
		"major": "Artificial Intelligence",
		"source": "Reference",
		"admission_year": "2026",
	}.items():
		if frappe.db.exists(REFERENCE_DOCTYPES[field], value):
			values[field] = value

	changed = False
	for field, value in values.items():
		if doc.get(field) != value:
			doc.set(field, value)
			changed = True
	if not any(row.school_year == "2025-2026" for row in doc.get("academic_results")):
		doc.append(
			"academic_results",
			{"school_year": "2025-2026", "grade": "10", "academic_rank": "Khá", "gpa": 8.8},
		)
		changed = True
	if not any(row.certificate_name == "IELTS Academic" for row in doc.get("language_certificates")):
		doc.append(
			"language_certificates",
			{
				"language": "Tiếng Anh",
				"certificate_name": "IELTS Academic",
				"score_level": "7.0",
				"issue_date": "2026-03-15",
				"expiry_date": "2028-03-15",
			},
		)
		changed = True
	if changed:
		doc.save(ignore_permissions=True)


def _ensure_interaction(student: str, spec: dict[str, Any]) -> str:
	external_id = f"{SEED_NAMESPACE}:interaction:{spec['key']}"
	existing = frappe.db.get_value("CRM Interaction", {"external_id": external_id}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"student": student,
				"interaction_type": _ensure_interaction_type("Student 360 Demo"),
				"interaction_datetime": spec["when"],
				"external_id": external_id,
				"source_namespace": SEED_NAMESPACE,
				"source_record_id": spec["key"],
				"channel": spec["channel"],
				"direction": spec["direction"],
				"actor": "Administrator",
				"summary": spec["summary"],
				"notes": spec["notes"],
				"outcome": spec["outcome"],
				"next_follow_up_action": spec.get("next_follow_up_action"),
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_assessment(student: str, interaction: str, spec: dict[str, Any]) -> str:
	model_version = f"{SEED_NAMESPACE}:{spec['key']}"
	existing = frappe.db.get_value(
		"CRM Student Assessment", {"student": student, "model_version": model_version}, "name"
	)
	if existing:
		return existing

	from crm.fcrm.student_assessment import record_student_assessment

	result = record_student_assessment(
		student,
		{
			"interest": spec["interest"],
			"interest_confidence": 88,
			"fit": spec["fit"],
			"fit_confidence": 84,
			"primary_barrier": spec["barrier"],
			"barrier_confidence": 78,
			"enrollment_probability": spec["probability"],
		},
		source="manual",
		reason=spec["reason"],
		evidence_references=[f"CRM Interaction:{interaction}"],
		model_version=model_version,
		confirm=True,
	)
	assessment = result["name"]
	frappe.db.set_value(
		"CRM Student Assessment",
		assessment,
		{
			"assessed_at": spec["when"],
			"confirmed_at": spec["when"],
			"signal_score": spec["signal_score"],
			"recommendation": spec["recommendation"],
		},
		update_modified=False,
	)
	return assessment


def _ensure_consent_and_parent(student: str) -> dict[str, str | None]:
	student_doc = frappe.get_doc("CRM Student", student)
	contact_email = "phu.huynh.giauyen@example.test"
	contact = frappe.db.get_value("CRM Contact", {"email": contact_email}, "name")
	if not contact:
		previous = frappe.flags.get("student_conversion_service")
		frappe.flags.student_conversion_service = True
		try:
			contact = (
				frappe.get_doc(
					{
						"doctype": "CRM Contact",
						"full_name": "Nguyễn Thị Hương",
						"phone": "0908000177",
						"email": contact_email,
						"enrollment_status": student_doc.enrollment_status or "NEW",
						"readiness_level": "Level 2 - Đang so sánh",
						"quality_bucket": "Warm",
						"is_verified_lead": 1,
						"decision_maker": "Parent",
						"preferred_contact_channel": "Email",
						"high_school": student_doc.high_school,
						"province": student_doc.province,
						"source": student_doc.source,
						"admission_year": student_doc.admission_year,
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		finally:
			frappe.flags.student_conversion_service = previous

	from crm.fcrm.student_parent_context import record_parent_contact_authority

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
			concerns="Quan tâm học phí và điều kiện học bổng.",
			lawful_basis="consent",
			allowed_channels=["Email"],
			proof_reference=f"{SEED_NAMESPACE}:parent-consent",
			effective_at=datetime(2026, 8, 21, 18, 30),
		)

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
					"preferred_channel": "Email",
					"best_contact_time": "19:00-20:30",
					"consent_summary": "Đã đồng ý nhận tư vấn tuyển sinh qua Email.",
					"consent_evidence": {"source": SEED_NAMESPACE, "authority": authority},
					"is_active": 1,
					"source_reference": f"{SEED_NAMESPACE}:guardian",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	consent_source = f"{SEED_NAMESPACE}:consent"
	if not frappe.db.exists("CRM Contact Consent Event", {"student": student, "source": consent_source}):
		frappe.get_doc(
			{
				"doctype": "CRM Contact Consent Event",
				"student": student,
				"event_type": "Granted",
				"occurred_at": datetime(2026, 8, 21, 18, 30),
				"granted_at": datetime(2026, 8, 21, 18, 30),
				"purpose": "admissions_processing",
				"scope": "email",
				"source": consent_source,
				"note": "Dữ liệu demo local; chỉ cho phép Email.",
			}
		).insert(ignore_permissions=True)

	return {"contact": contact, "authority": authority, "guardian": guardian}


def seed() -> dict[str, Any]:
	"""Create or enrich the selected local student and return seed metrics."""
	_assert_local_site()
	from crm.demo import seed_showcase

	with seed_showcase._temporary_local_flags():
		student = _resolve_student()
		_set_student_profile(student)
		interaction_names = [_ensure_interaction(student, spec) for spec in INTERACTIONS]
		assessment_names = [
			_ensure_assessment(student, interaction_names[index], spec)
			for index, spec in enumerate(ASSESSMENTS)
		]
		parent = _ensure_consent_and_parent(student)
		frappe.db.commit()
	return {
		"student": student,
		"student_name": STUDENT_NAME,
		"interactions": len(interaction_names),
		"assessments": len(assessment_names),
		"parent": parent,
		"channels": ["Website", "Sự kiện", "Hồ sơ"],
		"excluded": ["Zalo", "calls", "tasks"],
	}
