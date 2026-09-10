"""Seed one coherent, idempotent local CRM dataset.

The task seed deliberately composes the existing domain commands instead of
writing protected Lead fields directly.  It is the only seed entrypoint kept
in ``Taskfile.yml``: lookup data and campaigns first, role accounts and sales
topology second, then twenty Lead -> Student chains.
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

import frappe

from crm.demo import (
	school_domain_import,
	seed_ctv_sale,
	seed_demo,
	seed_golden,
	seed_lead_api_campaigns,
	seed_lead_api_lookups,
	seed_role_accounts,
	seed_showcase,
	seed_staff,
)

NAMESPACE = "crm-demo-task-seed-2026"
SEED_NOW = datetime(2026, 9, 8, 9, 0, 0)
LEAD_COUNT = 20
SCHOOLS_PER_PROVINCE = seed_lead_api_lookups.SCHOOLS_PER_PROVINCE
EXPECTED_PROVINCE_COUNT = 7
PROVINCE_SOURCE_CODES = {
	"Khánh Hoà": "56",
	"Đắk Lắk": "66",
	"Lâm Đồng": "68",
	"TP. Đồng Nai": "75",
	"Tp. Hồ Chí Minh": "79",
	"Tây Ninh": "80",
	"Đồng Tháp": "82",
}

OWNER_ACCOUNTS = (
	{
		"email": "ctvsale@gmail.com",
		"full_name": "Cộng tác viên Sale",
		"role": "CTV Sale",
		"function": "CTV Sale",
		"is_team_lead": False,
	},
	{
		"email": "sale@gmail.com",
		"full_name": "Nhân viên Tư vấn",
		"role": "Sale",
		"function": "Sale",
		"is_team_lead": False,
	},
	{
		"email": "leadsale@gmail.com",
		"full_name": "Trưởng nhóm Tư vấn",
		"role": "Lead Sale",
		"function": "Lead Sale",
		"is_team_lead": True,
	},
)

LEAD_NAMES = (
	"Nguyễn Minh Anh",
	"Trần Gia Hân",
	"Lê Hoàng Nam",
	"Phạm Khánh Linh",
	"Đỗ Minh Khang",
	"Võ Ngọc Mai",
	"Bùi Đức Anh",
	"Huỳnh Thảo Vy",
	"Phan Nhật Minh",
	"Đặng Hà My",
	"Ngô Quang Huy",
	"Trương Bảo Ngọc",
	"Dương Tuấn Kiệt",
	"Mai Hoài An",
	"Cao Minh Châu",
	"Lý Thanh Tâm",
	"Tạ Quốc Bảo",
	"Đinh Yến Nhi",
	"Hồ Anh Dũng",
	"Vũ Phương Thảo",
)

EVENT_TITLE = "Task Seed Open Day 2026"
ADMISSION_METHOD = "TRANSCRIPT_REVIEW"
PLATFORM_NAME = "Task Seed Website"

# The task seed is the supported local reset path for the Sales dashboard. Its
# records are consumed by the durable Student 360 and NBA runtimes, so their
# feature gates must survive the temporary seed flags after a successful seed.
LOCAL_AI_RUNTIME_CONFIG = {
	"crm_intelligence_runs_enabled": 1,
	"crm_intelligence_writer_epoch": 1,
	"crm_nba_evaluation_runtime_enabled": 1,
}


def _key(*parts: Any) -> str:
	return ":".join((NAMESPACE, *(str(part) for part in parts)))


def _ensure_admission_method() -> str:
	if frappe.db.exists("CRM Admission Method", ADMISSION_METHOD):
		return ADMISSION_METHOD
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Admission Method",
				"code": ADMISSION_METHOD,
				"display_name": "Xét học bạ",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_platform(source: str) -> str:
	platform = frappe.db.get_value("CRM Platform", {"platform_name": PLATFORM_NAME}, "name")
	if platform:
		return platform
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Platform",
				"platform_name": PLATFORM_NAME,
				"lead_source": source,
				"sub_channel": "Form",
				"approval_state": "Approved",
				"owner_role": "Marketing",
				"version": 1,
				"effective_date": "2026-01-01",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_event(campaign: str, campus: str) -> str:
	event = frappe.db.get_value("CRM Event", {"title": EVENT_TITLE}, "name")
	if event:
		frappe.db.set_value(
			"CRM Event",
			event,
			{"crm_campaign": campaign, "location": campus},
			update_modified=False,
		)
		return event
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Event",
				"title": EVENT_TITLE,
				"crm_campaign": campaign,
				"event_date": "2026-08-29",
				"location": campus,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _seed_campaign_domain() -> dict[str, Any]:
	"""Seed the public campaign lookups before creating accounts or Leads."""
	lookup = seed_lead_api_lookups.execute()
	provinces = lookup["provinces"]
	if len(provinces) != EXPECTED_PROVINCE_COUNT:
		raise frappe.ValidationError(
			f"Campaign lookup seed must provide {EXPECTED_PROVINCE_COUNT} provinces; got {len(provinces)}."
		)

	# ``_ensure_campus`` is reused only for the shared campus.  It does not seed
	# the old demo campaign, so the four public campaigns remain the campaign set
	# owned by this task.
	campus = seed_demo._ensure_campus(provinces[0])
	campaign_report = seed_lead_api_campaigns.execute(campus=campus)
	seed_demo._seed_intent_types()
	seed_demo._seed_signals()
	seed_demo._seed_score_template()

	admission_year = seed_demo._ensure_admission_year()
	education_program = seed_demo._ensure_education_program()
	aspiration = seed_demo._ensure_aspiration()
	source = seed_demo._ensure_lead_source()
	enrollment_status = seed_demo._ensure_enrollment_status("NEW")
	admission_method = _ensure_admission_method()
	platform = _ensure_platform(source)
	from crm.patches.v1_0.seed_crm_action_type import execute as seed_action_catalog

	seed_action_catalog()
	campaigns = campaign_report["campaigns"]
	event = _ensure_event(campaigns[2]["name"], campus)

	return {
		"campus": campus,
		"provinces": provinces,
		"campaigns": campaigns,
		"event": event,
		"admission_year": admission_year,
		"education_program": education_program,
		"aspiration": aspiration,
		"source": source,
		"enrollment_status": enrollment_status,
		"admission_method": admission_method,
		"platform": platform,
	}


def _seed_accounts(campus: str) -> dict[str, Any]:
	"""Create all role logins and the three-member Sale topology."""
	role_accounts = seed_role_accounts.execute()
	department = seed_staff._ensure_fixture_department(campus)
	team = seed_staff._ensure_fixture_sales_team(campus)
	pool = seed_staff._ensure_fixture_student_pool(team)
	staff_by_email: dict[str, str] = {}

	for account in OWNER_ACCOUNTS:
		spec = seed_ctv_sale.SalesAccountSeed(
			namespace=NAMESPACE,
			account_email=account["email"],
			account_full_name=account["full_name"],
			account_role=account["role"],
			password=seed_role_accounts.PASSWORD,
			team_membership_function=account["function"],
			student_scenarios=(),
			assign_students_to_account=False,
			is_team_lead=account["is_team_lead"],
		)
		seed_ctv_sale._ensure_user(spec)
		staff = seed_ctv_sale._ensure_staff(spec, campus, department)
		seed_ctv_sale._ensure_team_membership(spec, staff, team)
		staff_by_email[account["email"]] = staff

	seed_showcase._ensure_lifecycle_statuses()
	seed_showcase._ensure_policies(campus, pool)
	return {
		"role_accounts": role_accounts,
		"department": department,
		"team": team,
		"pool": pool,
		"staff_by_email": staff_by_email,
	}


def _resolve_seed_schools(provinces: list[str]) -> list[dict[str, Any]]:
	province_ids = []
	for province in provinces:
		province_id = frappe.db.get_value(
			"CRM Province", {"province_code": PROVINCE_SOURCE_CODES[province]}, "name"
		)
		province_id = province_id or frappe.db.get_value("CRM Province", {"province_name": province}, "name")
		province_id = province_id or frappe.db.exists("CRM Province", province)
		province_id = province_id or school_domain_import._existing_province(province)
		if not province_id:
			raise frappe.ValidationError(f"Không tìm thấy tỉnh/thành trong campaign seed: {province}.")
		province_ids.append(province_id)

	rows = frappe.get_all(
		"CRM High School",
		filters={"province": ["in", province_ids]},
		fields=["name", "school_name", "school_code", "province", "ward"],
		order_by="province asc, school_code asc, name asc",
		limit_page_length=0,
	)
	by_province: dict[str, list[dict[str, Any]]] = {province: [] for province in province_ids}
	for row in rows:
		by_province.setdefault(row.province, []).append(row)

	selected: list[dict[str, Any]] = []
	for province in province_ids:
		province_rows = by_province.get(province, [])[:SCHOOLS_PER_PROVINCE]
		if len(province_rows) != SCHOOLS_PER_PROVINCE:
			raise frappe.ValidationError(
				f"Tỉnh {province} phải có {SCHOOLS_PER_PROVINCE} trường cho campaign seed."
			)
		selected.extend(province_rows)
	return selected


def build_lead_profiles(
	schools: list[dict[str, Any]], campaigns: list[dict[str, Any]], context: dict[str, Any]
) -> list[dict[str, Any]]:
	"""Build deterministic synthetic profiles without embedding database state."""
	if len(schools) != EXPECTED_PROVINCE_COUNT * SCHOOLS_PER_PROVINCE:
		raise ValueError("The task seed requires exactly five selected schools per province.")
	if not campaigns:
		raise ValueError("At least one campaign is required to build Lead profiles.")

	profiles = []
	majors = [row["name"] for row in seed_lead_api_lookups.PUBLIC_LEAD_MAJORS]
	channels = ("Website", "Facebook", "Open Day", "Scholarship")
	profiles_by_campaign = [campaigns[index % len(campaigns)] for index in range(LEAD_COUNT)]

	for number, full_name in enumerate(LEAD_NAMES, start=1):
		school = schools[
			((number - 1) % EXPECTED_PROVINCE_COUNT) * SCHOOLS_PER_PROVINCE
			+ ((number - 1) // EXPECTED_PROVINCE_COUNT) % SCHOOLS_PER_PROVINCE
		]
		graduation_score = round(7.8 + (number % 5) * 0.25, 2)
		transcript_score = round(graduation_score + 0.15, 2)
		english_score = round(6.0 + (number % 4) * 0.5, 2)
		profile = {
			"key": f"lead-{number:02d}",
			"student_name": full_name,
			"student_email": f"task-seed-{number:02d}@example.test",
			"student_phone": f"090800{number:04d}",
			"gender": "Nam" if number % 2 else "Nữ",
			"date_of_birth": f"2008-{(number % 12) + 1:02d}-{(number % 18) + 10:02d}",
			"id_number": f"0792609{number:05d}",
			"id_issued_date": f"2024-{(number % 12) + 1:02d}-{(number % 18) + 10:02d}",
			"graduation_score": graduation_score,
			"transcript_score": transcript_score,
			"english_converted_score": english_score,
			"total_score": round(graduation_score + transcript_score + english_score, 2),
			"notes": (
				f"Hồ sơ demo {number:02d}: quan tâm {majors[(number - 1) % len(majors)]}, "
				"đã đồng ý nhận tư vấn tuyển sinh và cần theo dõi hồ sơ."
			),
			"parent": {
				"name": f"Phụ huynh {full_name}",
				"email": f"task-parent-{number:02d}@example.test",
				"phone": f"091800{number:04d}",
				"address": f"{school['province']} — khu vực {number:02d}",
				"relationship": "Parent",
			},
			"school": school,
			"major": majors[(number - 1) % len(majors)],
			"campaign": profiles_by_campaign[number - 1]["name"],
			"advertising_channel": channels[(number - 1) % len(channels)],
			"platform": context["platform"],
			"application": {
				"status": "Submitted",
				"document_completed": 5 + (number % 3),
				"scholarship_percentage": 10 if number % 3 == 0 else 0,
			},
			"assessment": {
				"interest": "High" if number % 3 else "Medium",
				"interest_confidence": 82 + number % 10,
				"fit": "High" if number % 4 else "Medium",
				"fit_confidence": 80 + number % 12,
				"primary_barrier": ("None", "Cost", "Information")[number % 3],
				"barrier_confidence": 72 + number % 15,
				"enrollment_probability": 68 + number % 25,
			},
			"assessment_reason": "Điểm học tập, tương tác campaign và nhu cầu tư vấn nhất quán.",
			"score": {
				"fit": 28 + number % 10,
				"engagement": 16 + number % 12,
				"intent": 24 + number % 18,
				"negative": -(number % 4),
			},
		}
		profiles.append(profile)
	return profiles


def _submit_lead(profile: dict[str, Any], context: dict[str, Any], pool: str) -> str:
	from crm.fcrm.student_intake import submit_intake

	source_id = _key("lead", profile["key"])
	existing = frappe.db.get_value("CRM Lead", {"import_source_id": source_id}, "name")
	if not existing:
		existing = frappe.db.get_value("CRM Lead", {"email": profile["student_email"]}, "name")
	if existing:
		return existing

	school = profile["school"]
	payload = {
		"student_name": profile["student_name"],
		"email": profile["student_email"],
		"phone": profile["student_phone"],
		"id_number": profile["id_number"],
		"gender": profile["gender"],
		"date_of_birth": profile["date_of_birth"],
		"admission_method": context["admission_method"],
		"campus": context["campus"],
		"owning_team": pool,
		"admission_year": context["admission_year"],
		"enrollment_status": context["enrollment_status"],
		"high_school": school["name"],
		"province": school["province"],
		"ward": school["ward"],
		"current_grade": "12",
		"study_stage": "grade_12_h2",
		"major": profile["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"advertising_channel": profile["advertising_channel"],
		"consent": {
			"granted": True,
			"granted_at": str(SEED_NOW - timedelta(days=9)),
			"purpose": "admissions_counseling",
			"scope": "student_profile_and_parent_follow_up",
			"source": NAMESPACE,
		},
		"alt_name": profile["parent"]["name"],
		"alt_phone": profile["parent"]["phone"],
	}
	result = submit_intake(
		payload,
		source_namespace=NAMESPACE,
		source_record_id=source_id,
		idempotency_key=_key("intake", profile["key"]),
		correlation_id=_key("correlation", profile["key"]),
	)
	if result.get("outcome") not in {"created", "attached"} or not result.get("student"):
		raise frappe.ValidationError(f"Student intake did not resolve for {profile['key']}: {result}")
	return result["student"]


def _set_child_row(doc: Any, table_field: str, identity_field: str, values: dict[str, Any]) -> None:
	identity = values[identity_field]
	row = next((item for item in doc.get(table_field) if item.get(identity_field) == identity), None)
	if row:
		for field, value in values.items():
			if row.get(field) != value:
				row.set(field, value)
		return
	doc.append(table_field, values)


def _complete_lead(lead: str, profile: dict[str, Any], context: dict[str, Any]) -> None:
	school = profile["school"]
	parent = profile["parent"]
	doc = frappe.get_doc("CRM Lead", lead)
	values = {
		"student_name": profile["student_name"],
		"phone": profile["student_phone"],
		"email": profile["student_email"],
		"gender": profile["gender"],
		"date_of_birth": profile["date_of_birth"],
		"enrollment_status": context["enrollment_status"],
		"admission_method": context["admission_method"],
		"branch": context["campus"],
		"high_school": school["name"],
		"province": school["province"],
		"ward": school["ward"],
		"current_grade": "12",
		"study_stage": "grade_12_h2",
		"major": profile["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"advertising_channel": profile["advertising_channel"],
		"campaign": profile["campaign"],
		"cohort_start_year": 2023,
		"cohort_end_year": 2026,
		"education_program": context["education_program"],
		"graduation_score": profile["graduation_score"],
		"transcript_score": profile["transcript_score"],
		"english_converted_score": profile["english_converted_score"],
		"total_score": profile["total_score"],
		"step": 3,
		"id_number": profile["id_number"],
		"id_issued_date": profile["id_issued_date"],
		"id_issued_place": "Cục Cảnh sát QLHC về TTXH",
		"conversion_potential": "High" if profile["assessment"]["fit"] == "High" else "Medium",
		"alt_name": parent["name"],
		"alt_phone": parent["phone"],
		"alt_address": parent["address"],
		"notes": profile["notes"],
		"import_source_id": _key("lead", profile["key"]),
	}
	for field, value in values.items():
		if doc.get(field) != value:
			doc.set(field, value)
	_set_child_row(
		doc,
		"academic_results",
		"school_year",
		{
			"school_year": "2025-2026",
			"grade": "12",
			"academic_rank": "Giỏi",
			"gpa": profile["transcript_score"],
		},
	)
	_set_child_row(
		doc,
		"academic_results",
		"school_year",
		{
			"school_year": "2024-2025",
			"grade": "11",
			"academic_rank": "Khá",
			"gpa": profile["graduation_score"],
		},
	)
	_set_child_row(
		doc,
		"language_certificates",
		"certificate_name",
		{
			"language": "Tiếng Anh",
			"certificate_name": "IELTS Academic",
			"score_level": str(profile["english_converted_score"]),
			"issue_date": "2025-08-20",
			"expiry_date": "2027-08-20",
		},
	)
	doc.save(ignore_permissions=True)


def _assign_lead(lead: str, staff: str, team: str, key: str) -> None:
	from crm.fcrm.lead_processing import ADVANCING_RESOLUTIONS, mark_lead_assigned, process_lead
	from crm.fcrm.student_ownership import change_student_ownership

	lead_doc = frappe.get_doc("CRM Lead", lead)
	processing_status = str(lead_doc.get("processing_status") or "NEW").upper()
	if processing_status == "NEW":
		process_lead(
			lead,
			reason="Unified task seed: kiểm tra dữ liệu trước khi phân công Lead.",
		)
		lead_doc = frappe.get_doc("CRM Lead", lead)
		processing_status = str(lead_doc.get("processing_status") or "NEW").upper()
	resolution = str(lead_doc.get("resolution") or "PENDING").upper()
	if processing_status not in {"PROCESSED", "ASSIGNED", "CLOSED"}:
		raise frappe.ValidationError(
			f"Lead {lead} must be processed before owner assignment; current status is {processing_status}."
		)
	if processing_status == "CLOSED" and resolution not in ADVANCING_RESOLUTIONS:
		raise frappe.ValidationError(f"Lead {lead} is closed with a non-assignable resolution: {resolution}.")

	current = frappe.db.get_value(
		"CRM Lead",
		lead,
		["owner_staff", "owning_team", "owning_pool", "ownership_revision"],
		as_dict=True,
	)
	# Owner assignment uses XOR topology: an owner target deliberately clears
	# owning_team and owning_pool.  A CLOSED Lead with an advancing resolution
	# is already converted, so it must remain CLOSED on an idempotent rerun.
	owner_is_current = current.owner_staff == staff and not current.owning_team and not current.owning_pool
	if owner_is_current:
		if processing_status == "PROCESSED":
			mark_lead_assigned(lead, reason="Unified task seed: ownership đã sẵn sàng.")
		return
	if not current.owning_pool and not current.owner_staff:
		raise frappe.ValidationError(f"Lead {lead} has no canonical pool before owner assignment.")
	change_student_ownership(
		student=lead,
		target_kind="owner",
		target_id=staff,
		target_team_id=team,
		reason="Unified task seed: phân công Lead cho CTV Sale hoặc Sale theo vòng.",
		idempotency_key=_key("assignment", key, f"r{current.ownership_revision or 0}"),
		expected_revision=int(current.ownership_revision or 0),
		correlation_id=_key("assignment-correlation", key),
		_internal_service=True,
		_internal_actor="Administrator",
		_commit=False,
	)
	if processing_status == "PROCESSED":
		mark_lead_assigned(lead, reason="Unified task seed: phân công Lead hoàn tất.")


def _ensure_contact(
	student: str, lead: str, profile: dict[str, Any], context: dict[str, Any], staff: str, team: str
) -> str:
	"""Enrich the canonical Student created by Lead conversion.

	A task-seed lead and its Student deliberately share one HS identifier.  Do
	not create a provisional Student here: ``_ensure_conversion`` owns that

	identity boundary and every downstream fixture must target its result.
	"""
	school = profile["school"]
	parent = profile["parent"]
	contact = str(student or "").strip()
	if not contact or not frappe.db.exists("CRM Student", contact):
		frappe.throw("Task seed requires the canonical converted CRM Student.")
	values = {
		"full_name": profile["student_name"],
		"phone": profile["student_phone"],
		"email": profile["student_email"],
		"gender": profile["gender"],
		"date_of_birth": profile["date_of_birth"],
		"id_number": profile["id_number"],
		"id_issued_date": profile["id_issued_date"],
		"id_issued_place": "Cục Cảnh sát QLHC về TTXH",
		"student": lead,
		"student_identity": frappe.db.get_value("CRM Lead", lead, "identity"),
		"enrollment_status": context["enrollment_status"],
		"student_stage": "Connected",
		"readiness_level": "Level 2 - Đang so sánh",
		"quality_bucket": "Warm",
		"is_verified_lead": 1,
		"assigned_to": staff,
		"owner_staff": staff,
		"owning_team": team,
		"admission_year": context["admission_year"],
		"branch": context["campus"],
		"high_school": school["name"],
		"province": school["province"],
		"ward": school["ward"],
		"major": profile["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"platform": profile["platform"],
		"current_grade": "12",
		"study_stage": "grade_12_h2",
		"decision_maker": "Student",
		"preferred_contact_channel": "Phone",
		"parent_name": parent["name"],
		"parent_phone": parent["phone"],
		"cohort_start_year": 2023,
		"cohort_end_year": 2026,
		"graduation_score": profile["graduation_score"],
		"transcript_score": profile["transcript_score"],
		"english_converted_score": profile["english_converted_score"],
		"total_score": profile["total_score"],
		"notes": profile["notes"],
	}
	previous = frappe.flags.get("student_conversion_service")
	frappe.flags.student_conversion_service = True
	try:
		frappe.db.set_value("CRM Student", contact, values, update_modified=False)
	finally:
		if previous is None:
			frappe.flags.pop("student_conversion_service", None)
		else:
			frappe.flags.student_conversion_service = previous

	seed_showcase._ensure_consent_event(contact, "Granted")
	return contact


def _ensure_interactions(contact: str, profile: dict[str, Any], owner_email: str) -> tuple[str, str, str]:
	from crm.fcrm.interaction_log import create_interaction

	interaction_specs = (
		("Website Visit", "Website", "inbound", "Đã tiếp nhận hồ sơ từ landing page campaign."),
		("Counseling", "Phone", "outbound", "Sale đã gọi tư vấn ngành và phương thức xét tuyển."),
		("Connected", "Phone", "inbound", "Lead phản hồi, xác nhận nhu cầu trao đổi tiếp."),
	)
	interactions = []
	for index, (interaction_type, channel, direction, summary) in enumerate(interaction_specs, start=1):
		interaction_type = seed_demo._ensure_interaction_type(interaction_type)
		external_id = _key("interaction", profile["key"], index)
		interaction = create_interaction(
			interaction_type=interaction_type,
			student=contact,
			crm_contact=contact,
			actor=owner_email,
			summary=summary,
			notes="Dữ liệu demo nội bộ, không gửi thông báo ra ngoài.",
			outcome="Captured" if index < 3 else "Follow Up Needed",
			interaction_datetime=SEED_NOW - timedelta(days=9 - index * 2),
			channel=channel,
			direction=direction,
			source_namespace=NAMESPACE,
			source_record_id=f"{profile['key']}:interaction:{index}",
			external_id=external_id,
		)
		if interaction:
			frappe.db.set_value("CRM Interaction", interaction, "crm_student", contact, update_modified=False)
		interactions.append(interaction)
	return tuple(interactions)  # type: ignore[return-value]


def _ensure_intents(
	contact: str, interactions: tuple[str, str, str], profile: dict[str, Any]
) -> tuple[str, str]:
	intent_specs = (
		(interactions[1], "TUITION", "Support", 84),
		(interactions[2], "MAJOR_INQUIRY", "Dominant", 92),
	)
	intents = []
	for interaction, intent_type, role, confidence in intent_specs:
		intent_type = seed_demo._ensure_intent_type(
			intent_type,
			"High" if intent_type == "TUITION" else "Medium",
			f"Task seed intent for {profile['key']}",
		)
		existing = frappe.db.get_value(
			"CRM Intent",
			{"interaction": interaction, "intent_type": intent_type, "intent_role": role},
			"name",
		)
		if not existing:
			existing = (
				frappe.get_doc(
					{
						"doctype": "CRM Intent",
						"interaction": interaction,
						"student": contact,
						"crm_student": contact,
						"intent_type": intent_type,
						"intent_role": role,
						"polarity": "Positive",
						"confidence": confidence,
						"notes": "Nhu cầu được xác định từ lịch sử tư vấn demo.",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		intents.append(existing)
	return tuple(intents)  # type: ignore[return-value]


def _ensure_offering(major: str, context: dict[str, Any]) -> str:
	from crm.fcrm.admission_offering import approve_offering

	filters = {
		"admission_year": context["admission_year"],
		"campus": context["campus"],
		"major": major,
		"admission_method": context["admission_method"],
		"status": "Active",
	}
	active = frappe.db.get_value("CRM Admission Offering", filters, "name")
	if active:
		return active

	offering_key = _key(
		"offering",
		context["admission_year"],
		context["campus"],
		major,
		context["admission_method"],
	)
	existing = frappe.db.get_value("CRM Admission Offering", {"offering_key": offering_key}, "name")
	if existing:
		offering = frappe.get_doc("CRM Admission Offering", existing)
	else:
		offering = frappe.get_doc(
			{
				"doctype": "CRM Admission Offering",
				"offering_key": offering_key,
				"admission_year": context["admission_year"],
				"campus": context["campus"],
				"major": major,
				"admission_method": context["admission_method"],
				"quota": 500,
				"effective_from": "2026-01-01",
				"effective_until": "2026-12-31",
				"status": "Draft",
			"policy_version": "admissions-offering",
				"source_reference": _key("offering-source", major),
			}
		).insert(ignore_permissions=True)
	if offering.status != "Active":
		approve_offering(
			offering=offering.name,
			idempotency_key=_key("offering-approval", major, context["admission_method"]),
		)
	return offering.name


def _ensure_application(
	lead: str,
	profile: dict[str, Any],
	context: dict[str, Any],
) -> str:
	from crm.fcrm.admission_application import create_application

	source_reference = _key("application", profile["key"])
	existing = frappe.db.get_value(
		"CRM Admission Application", {"source_reference": source_reference}, "name"
	)
	if existing:
		return existing
	offering = _ensure_offering(profile["major"], context)
	result = create_application(
		student=lead,
		values={
			"offering": offering,
			"status": profile["application"]["status"],
			"preference_order": 1,
			"preference": "Primary",
			"document_total": 8,
			"document_completed": profile["application"]["document_completed"],
			"scholarship_percentage": profile["application"]["scholarship_percentage"],
			"deadline": "2026-09-30",
			"submitted_at": SEED_NOW - timedelta(days=3),
			"source_reference": source_reference,
		},
		expected_revision=int(frappe.db.get_value("CRM Lead", lead, "engagement_revision") or 0),
		idempotency_key=source_reference,
	)
	return result["application"]


def _ensure_parent(lead: str, profile: dict[str, Any], context: dict[str, Any], team: str) -> dict[str, str]:
	from crm.fcrm.student_parent_context import record_parent_contact_authority

	parent = profile["parent"]
	parent_contact = frappe.db.get_value("CRM Student", {"email": parent["email"]}, "name")
	values = {
		"full_name": parent["name"],
		"phone": parent["phone"],
		"email": parent["email"],
		"enrollment_status": context["enrollment_status"],
		"readiness_level": "Level 2 - Đang so sánh",
		"quality_bucket": "Warm",
		"is_verified_lead": 1,
		"decision_maker": "Parent",
		"preferred_contact_channel": "Phone",
		"owning_team": team,
		"branch": context["campus"],
		"major": profile["major"],
		"high_school": profile["school"]["name"],
		"province": profile["school"]["province"],
		"source": context["source"],
		"admission_year": context["admission_year"],
	}
	previous = frappe.flags.get("student_conversion_service")
	frappe.flags.student_conversion_service = True
	try:
		if parent_contact:
			frappe.db.set_value("CRM Student", parent_contact, values, update_modified=False)
		else:
			parent_contact = (
				frappe.get_doc({"doctype": "CRM Student", **values}).insert(ignore_permissions=True).name
			)
	finally:
		if previous is None:
			frappe.flags.pop("student_conversion_service", None)
		else:
			frappe.flags.student_conversion_service = previous

	seed_showcase._ensure_consent_event(parent_contact, "Granted")
	authority = frappe.db.get_value(
		"CRM Parent Contact Authority",
		{"student": lead, "contact": parent_contact},
		"name",
	)
	if not authority:
		authority = record_parent_contact_authority(
			lead,
			parent_contact,
			relationship_type=parent["relationship"],
			decision_role="Primary decision maker",
			decision_influence="High",
			concerns="Quan tâm học phí, học bổng và thời hạn hoàn tất hồ sơ.",
			lawful_basis="consent",
			allowed_channels=["Phone", "Email", "Zalo"],
			proof_reference=_key("parent-consent", profile["key"]),
			effective_at=SEED_NOW - timedelta(days=8),
		)["name"]
	guardian = frappe.db.get_value(
		"CRM Student Guardian", {"student": lead, "contact": parent_contact}, "name"
	)
	if not guardian:
		guardian = (
			frappe.get_doc(
				{
					"doctype": "CRM Student Guardian",
					"student": lead,
					"contact": parent_contact,
					"relationship": "Parent",
					"decision_role": "Decision Maker",
					"involvement": "Primary",
					"preferred_channel": "Phone",
					"best_contact_time": "18:00-20:00",
					"consent_summary": "Đã xác nhận là đầu mối phụ huynh cho tư vấn tuyển sinh.",
					"consent_evidence": {"source": NAMESPACE, "authority": authority},
					"is_active": 1,
					"source_reference": _key("parent-guardian", profile["key"]),
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	return {"contact": parent_contact, "authority": authority, "guardian": guardian}


def _ensure_attribution(
	lead: str, contact: str, profile: dict[str, Any], context: dict[str, Any]
) -> dict[str, str]:
	from crm.fcrm.student_attribution import record_campaign_touchpoint, record_event_participation

	campaign_key = _key("campaign-touch", profile["key"])
	if not frappe.db.exists("CRM Marketing Engagement", {"idempotency_key": campaign_key}):
		record_campaign_touchpoint(
			lead,
			context["campaign"],
			crm_contact=contact,
			touched_at=SEED_NOW - timedelta(days=7),
			source="Manual",
			notes="Lead đến từ campaign seed và đã được gắn với hồ sơ tuyển sinh.",
			idempotency_key=campaign_key,
			correlation_id=_key("campaign-correlation", profile["key"]),
		)
	event_key = _key("event-participation", profile["key"])
	if not frappe.db.exists("CRM Marketing Engagement", {"idempotency_key": event_key}):
		record_event_participation(
			lead,
			context["event"],
			crm_contact=contact,
			status="Checked-in",
			registered_at=SEED_NOW - timedelta(days=5),
			checked_in_at=SEED_NOW - timedelta(days=5, hours=-1),
			feedback_rating=5,
			feedback_notes="Đã tham dự Open Day và trao đổi với chuyên viên tuyển sinh.",
			idempotency_key=event_key,
			correlation_id=_key("event-correlation", profile["key"]),
		)
	return {"campaign": context["campaign"], "event": context["event"]}


def _ensure_assessment(
	lead: str,
	interactions: tuple[str, str, str],
	intents: tuple[str, str],
	profile: dict[str, Any],
	application: str,
) -> str:
	from crm.fcrm.student_assessment import record_student_assessment

	existing = frappe.db.get_value("CRM Student Assessment", {"student": lead, "status": "confirmed"}, "name")
	if existing:
		return existing
	evidence = [
		f"CRM Interaction:{interactions[2]}",
		f"CRM Intent:{intents[1]}",
		f"CRM Admission Application:{application}",
	]
	result = record_student_assessment(
		lead,
		profile["assessment"],
		source="manual",
		reason=profile["assessment_reason"],
		evidence_references=evidence,
		model_version=f"{NAMESPACE}:{profile['key']}",
		confirm=True,
	)
	return result["name"]


def _ensure_score(student: str, profile: dict[str, Any]) -> str:
	from crm.api.scoring_write import append_local_fixture_score
	from crm.fcrm.scoring_policy import get_active_policy

	existing = frappe.db.get_value(
		"CRM Score History", {"student": student}, "name", order_by="creation desc"
	)
	if existing:
		return existing
	policy = get_active_policy()
	if not policy:
		raise frappe.ValidationError("Không có CRM scoring policy active cho task seed.")
	doc = frappe.get_doc("CRM Student", student)
	score = profile["score"]
	final_score = score["fit"] + score["engagement"] + score["intent"] + score["negative"]
	result = append_local_fixture_score(
		student=student,
		source_score_input_revision=int(doc.score_input_revision or 0),
		policy_revision=policy["policy_revision"],
		policy_hash=policy["policy_hash"],
		score_template=policy["template_id"],
		scoring_time=str(SEED_NOW),
		fit_score=score["fit"],
		engagement_score=score["engagement"],
		intent_score=score["intent"],
		time_decay_score=0,
		negative_score=score["negative"],
		final_score=final_score,
		score_change=final_score - float(doc.latest_score or 0),
		details=[
			{"category": "Fit", "signal": "Academic profile", "score": score["fit"]},
			{"category": "Engagement", "signal": "Campaign and event", "score": score["engagement"]},
			{"category": "Intent", "signal": "Major and tuition intent", "score": score["intent"]},
			{"category": "Negative", "signal": "Known friction", "score": score["negative"]},
		],
	)
	return result["history"]


def _ensure_conversion(lead: str, profile: dict[str, Any]) -> str:
	from crm.fcrm.student_conversion import convert_student

	doc = frappe.get_doc("CRM Lead", lead)
	if doc.get("converted_student") and frappe.db.exists("CRM Student", doc.converted_student):
		return doc.converted_student
	result = convert_student(
		student=lead,
		expected_lifecycle_revision=int(doc.lifecycle_revision or 0),
		idempotency_key=_key("conversion", profile["key"]),
		correlation_id=_key("conversion-correlation", profile["key"]),
	)
	student = result["contact"]
	# The next fixture writes Link-bearing records (score/action) against this
	# Student. Persist the conversion boundary first so Frappe cannot reuse a
	# negative Link-cache entry from before the Student was created.
	frappe.db.commit()
	frappe.clear_document_cache("CRM Student", student)
	return student


def _ensure_action(student: str, lead: str, staff: str, interaction: str, profile: dict[str, Any]) -> str:
	from crm.fcrm.student_decision import create_manual_action

	if frappe.db.get_value("CRM Student", student, "student") != lead:
		frappe.db.set_value("CRM Student", student, "student", lead, update_modified=False)
	existing = frappe.db.get_value(
		"CRM Action Item",
		{"student": student, "linked_interaction": interaction, "origin": "manual"},
		"name",
	)
	if existing:
		return existing
	result = create_manual_action(
		student=student,
		action_type="CALL",
		objective=f"Gọi lại {profile['student_name']} để chốt hồ sơ {profile['major']}.",
		idempotency_key=_key("action", profile["key"]),
		due_at=SEED_NOW + timedelta(days=1),
		priority="medium",
		assignee_staff=staff,
		linked_interaction=interaction,
	)
	return result["action"]


def owner_account_for_index(index: int) -> dict[str, Any]:
	"""Return the direct-owner account for a zero-based Lead index."""
	if index < 0:
		raise ValueError("Lead index must be non-negative.")
	return OWNER_ACCOUNTS[index % 2]


def _seed_one(
	profile: dict[str, Any], context: dict[str, Any], accounts: dict[str, Any], index: int
) -> dict[str, Any]:
	owner = owner_account_for_index(index)
	owner_staff = accounts["staff_by_email"][owner["email"]]
	lead = _submit_lead(profile, context, accounts["pool"])
	_complete_lead(lead, profile, context)
	_assign_lead(lead, owner_staff, accounts["team"], profile["key"])
	converted_student = _ensure_conversion(lead, profile)
	contact = _ensure_contact(converted_student, lead, profile, context, owner_staff, accounts["team"])
	interactions = _ensure_interactions(contact, profile, owner["email"])
	intents = _ensure_intents(contact, interactions, profile)
	application = _ensure_application(lead, profile, {**context, "campaign": profile["campaign"]})
	parent = _ensure_parent(lead, profile, context, accounts["team"])
	attribution = _ensure_attribution(
		lead,
		contact,
		profile,
		{**context, "campaign": profile["campaign"]},
	)
	assessment = _ensure_assessment(lead, interactions, intents, profile, application)
	score = _ensure_score(converted_student, profile)
	action = _ensure_action(converted_student, lead, owner_staff, interactions[2], profile)
	return {
		"key": profile["key"],
		"lead": lead,
		"student": converted_student,
		"owner_email": owner["email"],
		"owner_staff": owner_staff,
		"campaign": profile["campaign"],
		"school": profile["school"]["name"],
		"province": profile["school"]["province"],
		"major": profile["major"],
		"contact": contact,
		"parent": parent,
		"interactions": interactions,
		"intents": intents,
		"application": application,
		"attribution": attribution,
		"assessment": assessment,
		"score": score,
		"action": action,
	}


def verify() -> dict[str, Any]:
	"""Validate only the records owned by this task seed."""
	lead_rows = frappe.get_all(
		"CRM Lead",
		filters={"import_source_id": ["like", f"{NAMESPACE}:lead:%"]},
		fields=[
			"name",
			"student",
			"converted_student",
			"owner_staff",
			"assigned_to",
			"owning_team",
			"campaign",
			"province",
			"high_school",
		],
		limit_page_length=0,
	)
	if len(lead_rows) != LEAD_COUNT:
		raise frappe.ValidationError(f"Task seed expected {LEAD_COUNT} Leads; found {len(lead_rows)}.")
	student_names = {row.student for row in lead_rows if row.student}
	if len(student_names) != LEAD_COUNT:
		raise frappe.ValidationError("Task seed must produce one direct Student link for every Lead.")
	if any(not row.converted_student or row.converted_student != row.student for row in lead_rows):
		raise frappe.ValidationError("Every task Lead must be converted to its directly linked Student.")
	if any(not row.campaign or not row.high_school or not row.province for row in lead_rows):
		raise frappe.ValidationError("Every task Lead must have campaign and school geography links.")

	owner_staff = {row.owner_staff for row in lead_rows if row.owner_staff}
	if not owner_staff:
		raise frappe.ValidationError("Task seed produced no Lead owners.")
	owner_counts = Counter(frappe.db.get_value("CRM Staff", row.owner_staff, "user") for row in lead_rows)
	expected_owner_counts = {OWNER_ACCOUNTS[0]["email"]: 10, OWNER_ACCOUNTS[1]["email"]: 10}
	if owner_counts != expected_owner_counts:
		raise frappe.ValidationError(
			f"Task Lead owners must rotate 10/10 between CTV Sale and Sale; found {dict(owner_counts)}."
		)
	for row in lead_rows:
		staff = frappe.get_doc("CRM Staff", row.owner_staff)
		if not any(
			membership.function in {"Sale", "CTV Sale"}
			for membership in staff.team_memberships
			if membership.get("is_primary")
		):
			raise frappe.ValidationError(f"Lead {row.name} has an invalid direct owner.")
		if row.owner_staff != row.assigned_to:
			raise frappe.ValidationError(f"Lead {row.name} has inconsistent owner Staff/User projection.")

	province_count = len({row.province for row in lead_rows})
	campaign_count = len({row.campaign for row in lead_rows})
	if province_count != EXPECTED_PROVINCE_COUNT:
		raise frappe.ValidationError(
			f"Task Lead profiles must cover {EXPECTED_PROVINCE_COUNT} provinces; found {province_count}."
		)

	return {
		"leads": len(lead_rows),
		"students": len(student_names),
		"owner_counts": dict(owner_counts),
		"owner_staff": sorted(owner_staff),
		"campaigns_used": campaign_count,
		"provinces_used": province_count,
	}


def _persist_local_ai_runtime_config() -> None:
	"""Enable the runtimes required by the local task-seed walkthrough."""
	from frappe.installer import update_site_config

	for key, value in LOCAL_AI_RUNTIME_CONFIG.items():
		frappe.conf[key] = value
		update_site_config(key, value, validate=False)


def _ensure_local_ai_service_identity() -> dict[str, Any]:
	"""Restore the service principal used by inline 360/NBA execution."""
	return seed_golden._ensure_service_identity(
		os.environ.get("CRM_AGENTS_SERVICE_API_KEY"),
		os.environ.get("CRM_AGENTS_SERVICE_API_SECRET"),
	)


def seed() -> dict[str, Any]:
	"""Run the only supported local seed entrypoint."""
	seed_showcase._assert_local_site()
	seed_showcase.ensure_demo_config()
	seed_showcase.ensure_local_integrity_keys()
	frappe.set_user("Administrator")

	with seed_showcase._temporary_local_flags():
		campaign_context = _seed_campaign_domain()
		accounts = _seed_accounts(campaign_context["campus"])
		schools = _resolve_seed_schools(campaign_context["provinces"])
		profiles = build_lead_profiles(
			schools,
			campaign_context["campaigns"],
			campaign_context,
		)
		rows = []
		for index, profile in enumerate(profiles):
			rows.append(_seed_one(profile, campaign_context, accounts, index))
		frappe.db.commit()
		verification = verify()

	service_identity = _ensure_local_ai_service_identity()
	_persist_local_ai_runtime_config()

	result = {
		"namespace": NAMESPACE,
		"order": ["campaign_domain", "role_accounts", "leads", "students"],
		"campaign_domain": {
			"provinces": len(campaign_context["provinces"]),
			"schools": len(schools),
			"campaigns": campaign_context["campaigns"],
			"event": campaign_context["event"],
		},
		"accounts": {
			"roles": len(seed_role_accounts.ROLE_ACCOUNTS),
			"owners": [account["email"] for account in OWNER_ACCOUNTS[:2]],
			"lead_sales_supervisor": OWNER_ACCOUNTS[2]["email"],
			"team": accounts["team"],
			"pool": accounts["pool"],
		},
		"records": rows,
		"verification": verification,
		"service_identity": service_identity,
	}
	print(frappe.as_json(result))
	return result
