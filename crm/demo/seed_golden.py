"""Canonical lean demo seed: five students, two high schools, full CRM chain.

Run with::

    bench --site crm.localhost execute crm.demo.seed_golden.golden_seed
    bench --site crm.localhost execute crm.demo.seed_golden.verify

``golden_seed`` wipes nothing on its own (drive that with ``bench reinstall``);
it builds one integral, realistic dataset on top of a fresh site:

* master data + shared context (province, campus, major, admission year, ...)
* the six canonical role accounts (``role@gmail.com``) and the staff fixtures
* two ``CRM High School`` records with a Verified annual snapshot, stakeholders
  and field activities -- one high-potential, one still developing
* five ``CRM Student`` records spread across the whole funnel
  (Lead / MQL / Applicant / Enrolled / Lost), each with the complete raw CRM
  chain the admissions API and the AI features read: consent + geography
  snapshot on intake, three interactions, three intents, a qualification
  outcome, lifecycle events, an admission application where the stage warrants
  one, parent authority + guardian, marketing attribution, a confirmed
  assessment and a score-history row.

The students are seeded before the annual snapshots so the snapshot controller
picks up real funnel counts on its first insert.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import frappe

from crm.demo import seed_demo, seed_role_accounts, seed_staff

LOCAL_SITE = "crm.localhost"
SEED_NOW = datetime(2026, 9, 1, 10, 0, 0)

# The Sale fixture user that owns the seeded students and authors their
# interactions. This is the identity ``scripts/nba_live_e2e.py`` logs in as, so
# keeping ownership here is what lets a manual Next Best Action run read the
# student it was asked to analyse.
OWNER_USER = "nguyen.minh.khoi@gmail.com"

SERVICE_USER = "system@gmail.com"
SERVICE_USER_CONFIG_KEY = "crm_agents_service_user"


# ---------------------------------------------------------------------------
# High schools
# ---------------------------------------------------------------------------
# ``potential`` follows school_intelligence.potential_value_from_metrics:
# ne_actual / adjusted_ne_threshold >= 2 -> High, >= 1 -> Medium.

_SCHOOLS: dict[str, dict[str, Any]] = {
	"LHP": {
		"school_name": "THPT Chuyên Lê Hồng Phong",
		"school_code": "HCM-LHP",
		"address": "235 Nguyễn Văn Cừ, Quận 5, Thành phố Hồ Chí Minh",
		"ne_target": 28,
		"ne_actual": 30,
		"adjusted_ne_threshold": 10,
		"stakeholder": {
			"person": "Đặng Thị Ngọc Bích",
			"phone": "0902700001",
			"position_title": "Phó Hiệu trưởng phụ trách hướng nghiệp",
			"relationship_status": "Active",
			"influence": "Decision Maker",
			"relationship_score": 82,
		},
		"activities": (
			("Tư vấn hướng nghiệp tại trường", "Completed", "Positive", 180),
			("Gặp ban giám hiệu", "Completed", "Positive", 6),
			("Ngày hội tuyển sinh", "Planned", "Follow-up Needed", 0),
		),
	},
	"NTH": {
		"school_name": "THPT Nguyễn Thượng Hiền",
		"school_code": "HCM-NTH",
		"address": "544 Cách Mạng Tháng Tám, Quận Tân Bình, Thành phố Hồ Chí Minh",
		"ne_target": 18,
		"ne_actual": 12,
		"adjusted_ne_threshold": 10,
		"stakeholder": {
			"person": "Hoàng Văn Trung",
			"phone": "0902700002",
			"position_title": "Trưởng ban tư vấn tuyển sinh",
			"relationship_status": "New",
			"influence": "High",
			"relationship_score": 47,
		},
		"activities": (
			("Tư vấn hướng nghiệp tại trường", "Completed", "Follow-up Needed", 90),
			("Gặp ban giám hiệu", "Planned", "Follow-up Needed", 0),
		),
	},
}

_SCHOOL_SOURCE_RUN = "golden-seed:school-curation"


# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------

_PROFILES: list[dict[str, Any]] = [
	{
		"key": "gia-han",
		"namespace": "crm-demo-golden-gia-han",
		"student_name": "Phan Gia Hân",
		"student_email": "gia.han.golden@example.test",
		"student_phone": "0903700101",
		"gender": "Nữ",
		"date_of_birth": "2008-03-11",
		"id_number": "079308011021",
		"id_issued_date": "2024-03-20",
		"school": "LHP",
		"target_stage": "Lead",
		"outcome_code": "follow_up_required",
		"notes": "Học sinh mới đăng ký nhận thông tin, chưa tư vấn sâu.",
		"interactions": (
			"Đăng ký nhận thông tin ngành Software Engineering qua landing page.",
			"Chuyên viên gọi chào mừng, học sinh xin gửi tài liệu qua email.",
			"Học sinh mở email tài liệu, chưa đặt lịch tư vấn.",
		),
		"intents": (
			("Major Inquiry", "Dominant", 74),
			("Scholarship", "Support", 55),
			("Tuition", "Support", 40),
		),
		"outcome_next_action": "Gọi lại đặt lịch tư vấn lộ trình xét tuyển",
		"assessment": {
			"interest": "Medium",
			"interest_confidence": 62,
			"fit": "Medium",
			"fit_confidence": 58,
			"primary_barrier": "Information",
			"barrier_confidence": 66,
			"enrollment_probability": 34,
		},
		"assessment_reason": (
			"Học sinh mới tiếp cận, có quan tâm ngành nhưng chưa đủ tương tác để "
			"đánh giá mức độ phù hợp; cần thêm thông tin và một buổi tư vấn."
		),
		"parent": None,
		"application": None,
		"manual_action": None,
		"lost_reason": None,
		"score": {
			"fit": 18, "engagement": 12, "intent": 16, "negative": -2, "final": 44,
			"details": [
				{"category": "Fit", "signal": "Grade 12, chưa có học bạ đầy đủ", "score": 18},
				{"category": "Engagement", "signal": "Landing page + welcome call", "score": 12},
				{"category": "Intent", "signal": "Major inquiry", "score": 16},
				{"category": "Negative", "signal": "Chưa đặt lịch tư vấn", "score": -2},
			],
		},
	},
	{
		"key": "minh-anh",
		"namespace": "crm-demo-golden-minh-anh",
		"student_name": "Nguyễn Minh Anh",
		"student_email": "minh.anh.golden@example.test",
		"student_phone": "0903700102",
		"gender": "Nữ",
		"date_of_birth": "2008-04-15",
		"id_number": "079308012345",
		"id_issued_date": "2024-05-18",
		"school": "LHP",
		"target_stage": "MQL",
		"outcome_code": "qualified",
		"notes": "Học sinh quan tâm học bổng, cần chốt ngân sách với phụ huynh.",
		"interactions": (
			"Đăng ký nhận thông tin ngành Software Engineering và học bổng.",
			"Tư vấn lộ trình xét học bạ, học phí và điều kiện học bổng.",
			"Học sinh xác nhận muốn nộp hồ sơ và cần gọi phụ huynh chốt ngân sách.",
		),
		"intents": (
			("Major Inquiry", "Support", 84),
			("Scholarship", "Dominant", 96),
			("Tuition", "Support", 88),
		),
		"outcome_next_action": "Gọi phụ huynh xác nhận điều kiện học bổng và hồ sơ",
		"assessment": {
			"interest": "High",
			"interest_confidence": 91,
			"fit": "High",
			"fit_confidence": 86,
			"primary_barrier": "Cost",
			"barrier_confidence": 74,
			"enrollment_probability": 78,
		},
		"assessment_reason": (
			"Học sinh có GPA tốt, IELTS 7.5, đã tham dự campus visit và chủ động hỏi "
			"về học bổng; rào cản chính là ngân sách gia đình."
		),
		"parent": {
			"name": "Trần Thị Thu Hà",
			"email": "thu.ha.golden@example.test",
			"phone": "0908700102",
			"relationship": "Mẹ",
			"address": "Quận Bình Thạnh, Thành phố Hồ Chí Minh",
		},
		"application": None,
		"manual_action": {
			"type": "PARENT_CONTACT",
			"title": "Gọi phụ huynh xác nhận điều kiện học bổng và hồ sơ còn thiếu",
			"priority": "high",
		},
		"lost_reason": None,
		"score": {
			"fit": 34, "engagement": 27, "intent": 30, "negative": -4, "final": 87,
			"details": [
				{"category": "Fit", "signal": "Grade 12 + academic results", "score": 34},
				{"category": "Engagement", "signal": "Campus visit + counseling", "score": 27},
				{"category": "Intent", "signal": "Scholarship and major inquiry", "score": 30},
				{"category": "Negative", "signal": "Budget concern", "score": -4},
			],
		},
	},
	{
		"key": "thao-vy",
		"namespace": "crm-demo-golden-thao-vy",
		"student_name": "Lê Thảo Vy",
		"student_email": "thao.vy.golden@example.test",
		"student_phone": "0903700103",
		"gender": "Nữ",
		"date_of_birth": "2008-02-03",
		"id_number": "079308031592",
		"id_issued_date": "2024-04-02",
		"school": "NTH",
		"target_stage": "Applicant",
		"outcome_code": "qualified",
		"notes": "Học sinh đã nộp hồ sơ xét học bạ, còn thiếu giấy tờ công chứng.",
		"interactions": (
			"Nộp hồ sơ xét học bạ trực tuyến, còn thiếu học bạ bản sao công chứng.",
			"Tư vấn danh mục giấy tờ còn thiếu và thời hạn bổ sung.",
			"Học sinh xác nhận sẽ bổ sung giấy tờ trong tuần, cần nhắc lịch.",
		),
		"intents": (
			("Application Support", "Dominant", 95),
			("Scholarship", "Support", 70),
			("Major Inquiry", "Support", 58),
		),
		"outcome_next_action": "Nhắc học sinh bổ sung giấy tờ còn thiếu cho hồ sơ",
		"assessment": {
			"interest": "High",
			"interest_confidence": 90,
			"fit": "High",
			"fit_confidence": 83,
			"primary_barrier": "Information",
			"barrier_confidence": 81,
			"enrollment_probability": 72,
		},
		"assessment_reason": (
			"Học sinh đã chủ động nộp hồ sơ và có học lực tốt; rào cản chính là chưa "
			"nắm rõ danh mục giấy tờ cần bổ sung trước hạn."
		),
		"parent": {
			"name": "Lê Văn Thành",
			"email": "thanh.le.golden@example.test",
			"phone": "0908700103",
			"relationship": "Bố",
			"address": "Quận Tân Bình, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Under Review", "document_completed": 6, "scholarship_percentage": 20},
		"manual_action": None,
		"lost_reason": None,
		"score": {
			"fit": 32, "engagement": 26, "intent": 29, "negative": -3, "final": 84,
			"details": [
				{"category": "Fit", "signal": "Grade 12 + academic results", "score": 32},
				{"category": "Engagement", "signal": "Application submitted + counseling", "score": 26},
				{"category": "Intent", "signal": "Active application support requests", "score": 29},
				{"category": "Negative", "signal": "Missing documents", "score": -3},
			],
		},
	},
	{
		"key": "duc-huy",
		"namespace": "crm-demo-golden-duc-huy",
		"student_name": "Trần Đức Huy",
		"student_email": "duc.huy.golden@example.test",
		"student_phone": "0903700104",
		"gender": "Nam",
		"date_of_birth": "2008-07-22",
		"id_number": "079208027451",
		"id_issued_date": "2024-06-10",
		"school": "LHP",
		"target_stage": "Enrolled",
		"outcome_code": "qualified",
		"notes": "Học sinh đã hoàn tất hồ sơ, đóng phí giữ chỗ và xác nhận nhập học.",
		"interactions": (
			"Nộp hồ sơ xét học bạ đầy đủ, hỏi lịch đóng phí giữ chỗ.",
			"Tư vấn phương án học phí và xác nhận suất học.",
			"Học sinh xác nhận đã đóng phí giữ chỗ và sẽ nhập học đúng hạn.",
		),
		"intents": (
			("Tuition", "Dominant", 92),
			("Application Support", "Support", 74),
			("Scholarship", "Support", 61),
		),
		"outcome_next_action": "Xác nhận hồ sơ nhập học và lịch làm thủ tục",
		"assessment": {
			"interest": "High",
			"interest_confidence": 94,
			"fit": "High",
			"fit_confidence": 90,
			"primary_barrier": "None",
			"barrier_confidence": 80,
			"enrollment_probability": 95,
		},
		"assessment_reason": (
			"Học sinh có học lực tốt, hồ sơ đầy đủ và đã đóng phí giữ chỗ; không còn "
			"rào cản đáng kể cho việc nhập học."
		),
		"parent": {
			"name": "Phạm Thị Lan",
			"email": "lan.pham.golden@example.test",
			"phone": "0908700104",
			"relationship": "Mẹ",
			"address": "Quận 5, Thành phố Hồ Chí Minh",
		},
		"application": {"status": "Accepted", "document_completed": 8, "scholarship_percentage": 15},
		"manual_action": None,
		"lost_reason": None,
		"score": {
			"fit": 36, "engagement": 29, "intent": 31, "negative": 0, "final": 96,
			"details": [
				{"category": "Fit", "signal": "Grade 12 + academic results", "score": 36},
				{"category": "Engagement", "signal": "Full application + deposit paid", "score": 29},
				{"category": "Intent", "signal": "Tuition planning and enrolment intent", "score": 31},
				{"category": "Negative", "signal": "Không có rào cản", "score": 0},
			],
		},
	},
	{
		"key": "khanh-ngan",
		"namespace": "crm-demo-golden-khanh-ngan",
		"student_name": "Đỗ Khánh Ngân",
		"student_email": "khanh.ngan.golden@example.test",
		"student_phone": "0903700105",
		"gender": "Nữ",
		"date_of_birth": "2008-09-30",
		"id_number": "079308093310",
		"id_issued_date": "2024-02-14",
		"school": "NTH",
		"target_stage": "Lost",
		"outcome_code": "qualified",
		"notes": "Học sinh đủ điều kiện nhưng chọn nhập học trường khác.",
		"interactions": (
			"Đăng ký tư vấn ngành Data Science, đang cân nhắc nhiều trường.",
			"Tư vấn học phí, học bổng và so sánh chương trình với trường khác.",
			"Học sinh thông báo đã nhận học bổng toàn phần ở trường khác và rút hồ sơ.",
		),
		"intents": (
			("Major Inquiry", "Dominant", 88),
			("Scholarship", "Support", 83),
			("Tuition", "Support", 66),
		),
		"outcome_next_action": "Ghi nhận lý do và giữ liên hệ cho kỳ tuyển sinh sau",
		"assessment": {
			"interest": "High",
			"interest_confidence": 85,
			"fit": "High",
			"fit_confidence": 82,
			"primary_barrier": "Competition",
			"barrier_confidence": 88,
			"enrollment_probability": 20,
		},
		"assessment_reason": (
			"Học sinh phù hợp và tương tác tốt nhưng nhận học bổng toàn phần từ một "
			"trường cạnh tranh; rào cản chính là ưu đãi của đối thủ."
		),
		"parent": {
			"name": "Đỗ Quang Minh",
			"email": "quang.minh.golden@example.test",
			"phone": "0908700105",
			"relationship": "Bố",
			"address": "Quận Tân Bình, Thành phố Hồ Chí Minh",
		},
		"application": None,
		"manual_action": None,
		"lost_reason": "Học sinh nhận học bổng toàn phần từ một trường cạnh tranh và rút hồ sơ.",
		"score": {
			"fit": 33, "engagement": 24, "intent": 28, "negative": -12, "final": 61,
			"details": [
				{"category": "Fit", "signal": "Grade 12 + academic results", "score": 33},
				{"category": "Engagement", "signal": "Counseling + comparison session", "score": 24},
				{"category": "Intent", "signal": "Scholarship and major inquiry", "score": 28},
				{"category": "Negative", "signal": "Chọn trường cạnh tranh", "score": -12},
			],
		},
	},
]

# Mutated by ``_run_student`` for the duration of one profile seed.
_ACTIVE: dict[str, Any] = _PROFILES[0]

_LIFECYCLE_ORDER = ["Lead", "MQL", "Applicant", "Enrolled"]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) == LOCAL_SITE or frappe.conf.get("allow_demo_seed"):
		return
	frappe.throw(
		"golden_seed only runs on crm.localhost. Set allow_demo_seed=1 to opt in "
		"a demo/staging site.",
		frappe.PermissionError,
	)


def _ns() -> str:
	return _ACTIVE["namespace"]


def _key(*parts: Any) -> str:
	return ":".join((_ns(), *(str(part) for part in parts)))


def _correlation() -> str:
	return _key("student", _ACTIVE["key"])


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
	return seed_demo._ensure_intent_type(name, importance, f"Golden seed fixture: {name}")


# ---------------------------------------------------------------------------
# High schools
# ---------------------------------------------------------------------------


def _ensure_schools(context: dict[str, Any]) -> dict[str, str]:
	"""Create the two high schools without their snapshots.

	The snapshot controller computes funnel counts from real students on its
	first insert, so snapshots are added later by :func:`_finalise_schools`.
	"""
	province = context["province"]
	ward = context["ward"]
	resolved: dict[str, str] = {}
	for slug, spec in _SCHOOLS.items():
		name = frappe.db.get_value("CRM High School", {"school_code": spec["school_code"]}, "name")
		if not name:
			name = (
				frappe.get_doc(
					{
						"doctype": "CRM High School",
						"school_name": spec["school_name"],
						"school_code": spec["school_code"],
						"province": province,
						"ward": ward,
						"address": spec["address"],
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		resolved[slug] = name
	return resolved


def _finalise_schools(
	schools: dict[str, str], context: dict[str, Any], owner_staff: str | None
) -> dict[str, Any]:
	from frappe.utils import now_datetime

	role_term = _ensure_term("Đầu mối tuyển sinh", "stakeholder_role")
	summary: dict[str, Any] = {}
	for slug, school in schools.items():
		spec = _SCHOOLS[slug]

		# Verified annual snapshot -> drives School 360 potential-value evidence.
		frappe.db.delete("CRM High School Annual Snapshot", {"high_school": school})
		snapshot = frappe.get_doc(
			{
				"doctype": "CRM High School Annual Snapshot",
				"high_school": school,
				"admission_year": context["admission_year"],
				"ne_target": spec["ne_target"],
				"ne_actual": spec["ne_actual"],
				"adjusted_ne_threshold": spec["adjusted_ne_threshold"],
				"ne_actual_semantics": "Official Achieved New Enter",
				"verification_status": "Verified",
				"is_locked": 1,
				"source_system": "demo-seed",
				"source_run": _SCHOOL_SOURCE_RUN,
			}
		).insert(ignore_permissions=True)

		# Primary stakeholder -> drives School 360 relationship evidence.
		stk = spec["stakeholder"]
		person = _ensure_person(stk["person"], stk["phone"])
		association = frappe.db.get_value(
			"CRM School Stakeholder", {"high_school": school, "person": person}, "name"
		)
		values = {
			"high_school": school,
			"person": person,
			"stakeholder_role": role_term,
			"influence": stk["influence"],
			"owner_staff": owner_staff,
			"position_title": stk["position_title"],
			"is_primary": 1,
			"relationship_score": stk["relationship_score"],
			"last_touch_date": now_datetime().date() - timedelta(days=9),
			"next_touch_date": now_datetime().date() + timedelta(days=12),
			"contact_preference": "Phone",
			"source_note": "golden seed school relationship fixture",
		}
		if association:
			frappe.db.set_value("CRM School Stakeholder", association, values, update_modified=False)
		else:
			association = frappe.get_doc({"doctype": "CRM School Stakeholder", **values}).insert(
				ignore_permissions=True
			).name
		# relationship_status is governed; the seed only needs the value present.
		frappe.db.set_value(
			"CRM School Stakeholder",
			association,
			{"relationship_status": stk["relationship_status"]},
			update_modified=False,
		)

		# Field activities -> drives School 360 recent-activity evidence.
		for offset, (activity_type, status, outcome, attendance) in enumerate(spec["activities"]):
			activity_term = _ensure_term(activity_type, "activity_type")
			activity_date = now_datetime().date() - timedelta(days=30 - offset * 12)
			filters = {
				"high_school": school,
				"activity_type": activity_term,
				"activity_date": activity_date,
				"owner_staff": owner_staff,
			}
			row = frappe.db.get_value("CRM School Activity", filters, "name")
			payload = {**filters, "status": status, "outcome": outcome, "attendance": attendance}
			if row:
				frappe.db.set_value("CRM School Activity", row, payload, update_modified=False)
			else:
				frappe.get_doc({"doctype": "CRM School Activity", **payload}).insert(
					ignore_permissions=True
				)

		frappe.get_doc("CRM High School", school).save(ignore_permissions=True)
		summary[slug] = {
			"high_school": school,
			"snapshot": snapshot.name,
			"key_account_eligible": snapshot.get("key_account_eligible"),
			"stakeholder": association,
			"activities": len(spec["activities"]),
		}
	frappe.db.commit()
	return summary


def _ensure_term(name: str, category: str) -> str:
	existing = frappe.db.get_value("CRM Term", {"term_name": name, "category": category}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "CRM Term", "term_name": name, "category": category})
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_person(full_name: str, phone: str) -> str:
	existing = frappe.db.get_value("CRM Person", {"phone": phone}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc({"doctype": "CRM Person", "full_name": full_name, "phone": phone})
		.insert(ignore_permissions=True)
		.name
	)


# ---------------------------------------------------------------------------
# Per-student chain
# ---------------------------------------------------------------------------


def _submit_student(context: dict[str, Any], pool: str, high_school: str) -> str:
	from crm.fcrm.student_intake import submit_intake

	email = _ACTIVE["student_email"]
	payload = {
		"student_name": _ACTIVE["student_name"],
		"email": email,
		"phone": _ACTIVE["student_phone"],
		"id_number": _ACTIVE["id_number"],
		"gender": _ACTIVE["gender"],
		"date_of_birth": _ACTIVE["date_of_birth"],
		"admission_method": "Transcript Review",
		"campus": context["campus"],
		"owning_team": pool,
		"admission_year": context["admission_year"],
		"enrollment_status": context["enrollment_status"],
		"high_school": high_school,
		"province": context["province"],
		"ward": context["ward"],
		"current_grade": "12",
		"study_stage": "grade_12_h2",
		"major": context["major"],
		"aspiration": context["aspiration"],
		"source": context["source"],
		"advertising_channel": "Facebook Ads - Scholarship 2026",
		"consent": {
			"granted": True,
			"granted_at": str(SEED_NOW - timedelta(days=9)),
			"purpose": "admissions_counseling",
			"scope": "student_profile_and_parent_follow_up",
			"source": _ns(),
		},
	}
	parent = _ACTIVE.get("parent")
	if parent:
		payload["alt_name"] = parent["name"]
		payload["alt_phone"] = parent["phone"]

	existing = frappe.db.get_value("CRM Student", {"email": email}, "name")
	if existing:
		return existing

	result = submit_intake(
		payload,
		source_namespace=_ns(),
		source_record_id=f"student:{_ACTIVE['key']}",
		idempotency_key=_key("intake", f"student:{_ACTIVE['key']}"),
		correlation_id=_correlation(),
	)
	if result.get("outcome") not in {"created", "attached"} or not result.get("student"):
		frappe.throw(f"Student intake did not resolve: {result}", frappe.ValidationError)
	return result["student"]


def _complete_student_profile(student: str, context: dict[str, Any]) -> None:
	doc = frappe.get_doc("CRM Student", student)
	parent = _ACTIVE.get("parent")
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
		"id_number": _ACTIVE["id_number"],
		"id_issued_date": _ACTIVE["id_issued_date"],
		"id_issued_place": "Cục Cảnh sát QLHC về TTXH",
		"import_source_id": f"{_ns()}:student:{_ACTIVE['key']}",
		"notes": _ACTIVE["notes"],
	}
	if parent:
		values["alt_name"] = parent["name"]
		values["alt_phone"] = parent["phone"]
		values["alt_address"] = parent["address"]
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
				"source_namespace": _ns(),
				"source_record_id": key,
				"channel": channel,
				"direction": direction,
				"actor": OWNER_USER,
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


def _ensure_file(student: str) -> str:
	file_name = f"{_ns()}-phieu-tiep-nhan-ho-so.txt"
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
				"content": f"Phiếu tiếp nhận hồ sơ tuyển sinh demo\nHọc sinh: {_ACTIVE['student_name']}\n",
				"attached_to_doctype": "CRM Student",
				"attached_to_name": student,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_outcome(student: str, interaction: str, evidence_file: str) -> str:
	from crm.fcrm.student_engagement import record_outcome

	source_key = _key("outcome", "primary")
	existing = frappe.db.get_value("CRM Student Outcome", {"source_key": source_key}, "name")
	if existing:
		return existing
	result = record_outcome(
		student=student,
		interaction=interaction,
		outcome_code=_ACTIVE["outcome_code"],
		continuity_kind="task",
		next_action={"title": _ACTIVE["outcome_next_action"]},
		next_action_assignee=OWNER_USER,
		next_action_due_at=SEED_NOW + timedelta(days=1),
		qualification_evidence=[{"category": "document", "doctype": "File", "name": evidence_file}],
		source_key=source_key,
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key=source_key,
		correlation_id=_correlation(),
	)
	return result["event"]


def _ensure_lifecycle(student: str, outcome: str, intent: str, evidence_file: str) -> list[str]:
	from crm.fcrm.student_lifecycle import request_transition

	target = _ACTIVE["target_stage"]
	if target == "Lead":
		return []
	forward_target = "MQL" if target == "Lost" else target
	evidence_by_stage = {
		"MQL": [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
			{"category": "intent", "doctype": "CRM Intent", "name": intent},
		],
		"Applicant": [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
			{"category": "document", "doctype": "File", "name": evidence_file},
		],
		"Enrolled": [
			{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
			{"category": "document", "doctype": "File", "name": evidence_file},
		],
	}
	walked: list[str] = []
	for stage in _LIFECYCLE_ORDER[1 : _LIFECYCLE_ORDER.index(forward_target) + 1]:
		doc = frappe.get_doc("CRM Student", student)
		current = doc.lifecycle_stage or "Lead"
		if current == stage or _LIFECYCLE_ORDER.index(current) >= _LIFECYCLE_ORDER.index(stage):
			continue
		request_transition(
			student,
			stage,
			reason=f"Đủ bằng chứng nghiệp vụ để chuyển học sinh sang {stage}.",
			evidence_refs=evidence_by_stage[stage],
			outcome_code="qualified",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_key("lifecycle", stage),
			correlation_id=_correlation(),
		)
		walked.append(stage)
	if target == "Lost":
		doc = frappe.get_doc("CRM Student", student)
		if doc.lifecycle_stage != "Lost":
			request_transition(
				student,
				"Lost",
				reason=_ACTIVE["lost_reason"],
				expected_revision=int(doc.lifecycle_revision or 0),
				idempotency_key=_key("lifecycle", "lost"),
				correlation_id=_correlation(),
			)
			walked.append("Lost")
	return walked


def _ensure_application(student: str, context: dict[str, Any]) -> str | None:
	spec = _ACTIVE.get("application")
	if not spec:
		return None
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
			"status": spec["status"],
			"preference_order": 1,
			"preference": "Primary",
			"document_total": 8,
			"document_completed": spec["document_completed"],
			"scholarship_percentage": spec["scholarship_percentage"],
			"deadline": "2026-09-30",
			"submitted_at": SEED_NOW - timedelta(days=3),
			"source_reference": source_reference,
		},
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key=source_reference,
	)
	return result["application"]


def _ensure_parent(student: str, context: dict[str, Any], team: str, high_school: str) -> dict[str, str] | None:
	spec = _ACTIVE.get("parent")
	if not spec:
		return None
	from crm.fcrm.student_parent_context import record_parent_contact_authority

	parent_email = spec["email"]
	contact = frappe.db.get_value("CRM Contact", {"email": parent_email}, "name")
	if not contact:
		previous = frappe.flags.get("student_conversion_service")
		frappe.flags.student_conversion_service = True
		try:
			contact = (
				frappe.get_doc(
					{
						"doctype": "CRM Contact",
						"full_name": spec["name"],
						"phone": spec["phone"],
						"email": parent_email,
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
						"high_school": high_school,
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
			relationship_type=spec["relationship"],
			decision_role="Primary decision maker",
			decision_influence="High",
			concerns="Quan tâm học phí, học bổng và thời hạn hoàn tất hồ sơ.",
			lawful_basis="consent",
			allowed_channels=["Phone", "Email", "Zalo"],
			proof_reference=f"{_ns()}:parent-consent",
			effective_at=SEED_NOW - timedelta(days=8),
		)["name"]
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
					"consent_evidence": {"source": _ns(), "authority": authority},
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
		dict(_ACTIVE["assessment"]),
		source="manual",
		reason=_ACTIVE["assessment_reason"],
		evidence_references=evidence,
		model_version="golden-seed-2026.09",
		confirm=True,
	)
	return result["name"]


def _ensure_action(student: str, owner_staff: str) -> str | None:
	spec = _ACTIVE.get("manual_action")
	if not spec:
		return None
	from crm.fcrm.student_decision import _command_key, create_manual_action

	idempotency_key = _key("action", "manual")
	command_key = _command_key("manual_action", "Administrator", idempotency_key)
	existing = frappe.db.get_value("CRM Action", {"generation_idempotency_key": command_key}, "name")
	if existing:
		return existing
	return create_manual_action(
		student,
		spec["type"],
		spec["title"],
		idempotency_key=idempotency_key,
		due_at=SEED_NOW + timedelta(days=1),
		priority=spec.get("priority", "high"),
		assignee_staff=owner_staff,
	)["action"]


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
	spec = _ACTIVE["score"]
	result = append_local_fixture_score(
		student=student,
		source_score_input_revision=int(doc.score_input_revision or 0),
		policy_revision=policy["policy_revision"],
		policy_hash=policy["policy_hash"],
		score_template=policy["template_id"],
		scoring_time=str(SEED_NOW),
		fit_score=spec["fit"],
		engagement_score=spec["engagement"],
		intent_score=spec["intent"],
		time_decay_score=0,
		negative_score=spec["negative"],
		final_score=spec["final"],
		score_change=spec["final"] - float(doc.latest_score or 0),
		details=spec["details"],
	)
	return result.get("history") or ""


def _run_student(
	context: dict[str, Any], staff_context: dict[str, Any], schools: dict[str, str]
) -> dict[str, Any]:
	from crm.demo import seed_showcase

	high_school = schools[_ACTIVE["school"]]
	student = _submit_student(context, staff_context["pool"], high_school)
	_complete_student_profile(student, context)
	owner_staff = frappe.db.get_value("CRM Student", student, "owner_staff")
	if not owner_staff:
		owner_staff = seed_showcase._ensure_assigned(student)
	frappe.db.commit()

	_ensure_interaction(
		student, "website-form", "Website Visit", SEED_NOW - timedelta(days=8),
		"Website form", "inbound", _ACTIVE["interactions"][0],
	)
	interaction_counseling = _ensure_interaction(
		student, "initial-counseling", "Counseling", SEED_NOW - timedelta(days=6),
		"Phone", "outbound", _ACTIVE["interactions"][1],
	)
	interaction_latest = _ensure_interaction(
		student, "follow-up", "Connected", SEED_NOW - timedelta(days=2),
		"Phone", "inbound", _ACTIVE["interactions"][2],
	)
	intents = _ACTIVE["intents"]
	intent_first = _ensure_intent(student, interaction_counseling, *intents[0])
	intent_dominant = _ensure_intent(student, interaction_latest, *intents[1])
	_ensure_intent(student, interaction_latest, *intents[2])

	evidence_file = _ensure_file(student)
	outcome = _ensure_outcome(student, interaction_latest, evidence_file)
	walked = _ensure_lifecycle(student, outcome, intent_dominant, evidence_file)
	application = _ensure_application(student, context)
	parent = _ensure_parent(student, context, staff_context["team"], high_school)
	attribution = _ensure_attribution(student, context)
	assessment = _ensure_assessment(student, interaction_latest, intent_dominant, application)
	action = _ensure_action(student, owner_staff)
	score = _ensure_score(student)
	frappe.db.commit()

	return {
		"variant": _ACTIVE["key"],
		"student": student,
		"student_name": frappe.db.get_value("CRM Student", student, "student_name"),
		"high_school": high_school,
		"target_stage": _ACTIVE["target_stage"],
		"lifecycle_stage": frappe.db.get_value("CRM Student", student, "lifecycle_stage"),
		"lifecycle_walk": walked,
		"owner_staff": owner_staff,
		"application": application,
		"parent": parent,
		"assessment": assessment,
		"action": action,
		"score_history": score,
		"attribution": attribution,
		"dominant_intent": intent_dominant,
		"first_intent": intent_first,
		"outcome": outcome,
		"counts": {
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
		},
	}


# ---------------------------------------------------------------------------
# crm-agents service identity
# ---------------------------------------------------------------------------


def _ensure_service_identity(service_api_key: str | None, service_api_secret: str | None) -> dict[str, Any]:
	"""Point ``crm_agents_service_user`` at ``system@gmail.com``.

	``bench reinstall`` drops the Frappe User backing the crm-agents service
	token, which then 401s every non-chat analysis call. seed_role_accounts has
	already created ``system@gmail.com`` (System Manager); when the caller passes
	the API key/secret the crm-agents container is configured with, wire them
	onto that user so service calls authenticate again.
	"""
	from frappe.utils.password import set_encrypted_password

	if not frappe.db.exists("User", SERVICE_USER):
		return {"service_user": SERVICE_USER, "state": "missing-user"}

	_set_site_config(SERVICE_USER_CONFIG_KEY, SERVICE_USER)

	state = "user-linked"
	if service_api_key and service_api_secret:
		frappe.db.set_value("User", SERVICE_USER, "api_key", service_api_key, update_modified=False)
		set_encrypted_password("User", SERVICE_USER, service_api_secret, "api_secret")
		state = "credentials-synced"
	frappe.db.commit()
	return {"service_user": SERVICE_USER, "state": state}


def _set_site_config(key: str, value: Any) -> None:
	frappe.conf[key] = value
	try:
		from frappe.installer import update_site_config

		update_site_config(key, value, validate=False)
	except Exception:
		# Non-fatal: the in-process conf override still lets this run finish; the
		# operator can persist the value with `bench set-config` if needed.
		frappe.log_error("golden_seed: could not persist site config", key)


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------


ADMISSION_METHOD = "Transcript Review"


def _ensure_admission_method(name: str) -> None:
	"""Canonical admission method Term the admission offering links to."""
	if frappe.db.exists("CRM Term", {"term_name": name, "category": "admission_method"}):
		return
	from crm.fcrm.master_data_governance import create_additive_value

	create_additive_value(
		"CRM Term",
		name,
		reason="Canonical admission method used by the golden demo dataset.",
		idempotency_key=f"golden-seed:admission-method:{name}",
		correlation_id="golden-seed",
		category="admission_method",
	)


def _bootstrap() -> tuple[dict[str, Any], dict[str, Any]]:
	from crm.demo import seed_showcase

	seed_showcase.ensure_local_integrity_keys()
	seed_showcase.ensure_demo_config()
	seed_role_accounts.execute()
	context = seed_demo._bootstrap()
	staff_context = seed_staff._bootstrap()
	seed_showcase._ensure_lifecycle_statuses()
	seed_showcase._ensure_policies(staff_context["campus"], staff_context["pool"])
	_ensure_admission_method(ADMISSION_METHOD)
	frappe.db.commit()
	return context, staff_context


def golden_seed(
	service_api_key: str | None = None, service_api_secret: str | None = None
) -> dict[str, Any]:
	"""Seed the canonical lean demo dataset on ``crm.localhost``."""
	global _ACTIVE

	_assert_local_site()
	frappe.set_user("Administrator")

	with _seed_flags():
		context, staff_context = _bootstrap()
		# The Admissions Director fixture staff owns the school relationships;
		# seed_staff creates no dedicated promoter staff on the lean site.
		school_owner_staff = staff_context["staff_by_user"].get("tran.quoc.duy@gmail.com")
		schools = _ensure_schools(context)
		frappe.db.commit()

		students: list[dict[str, Any]] = []
		for profile in _PROFILES:
			_ACTIVE = profile
			try:
				students.append(_run_student(context, staff_context, schools))
			finally:
				_ACTIVE = _PROFILES[0]

		# Snapshots after the students so the controller sees real funnel counts.
		school_summary = _finalise_schools(schools, context, school_owner_staff)

	service = _ensure_service_identity(service_api_key, service_api_secret)

	result = {
		"ok": True,
		"students": students,
		"schools": school_summary,
		"service_identity": service,
		"role_accounts": [email for _, email, _ in seed_role_accounts.ROLE_ACCOUNTS],
	}
	print(frappe.as_json(result))
	return result


def verify() -> dict[str, Any]:
	"""Read-only check that the golden dataset is present and coherent."""
	from crm.api.student_context import get_student_context

	students = []
	for profile in _PROFILES:
		name = frappe.db.get_value("CRM Student", {"email": profile["student_email"]}, "name")
		if not name:
			students.append({"variant": profile["key"], "seeded": False})
			continue
		ctx = get_student_context(name, history_limit=50)
		students.append(
			{
				"variant": profile["key"],
				"seeded": True,
				"student": name,
				"stage": ctx["lifecycle"]["stage"],
				"expected_stage": profile["target_stage"],
				"stage_ok": ctx["lifecycle"]["stage"] == profile["target_stage"],
				"latest_interaction": bool(ctx["latest_interaction"]),
				"latest_outcome": bool(ctx["latest_outcome"]),
				"assessment": bool(ctx["assessment"].get("current")),
				"parent_context": len(ctx["parent_context"]),
				"score_state": ctx["admissions_context"]["score"].get("state"),
				"history_count": len(ctx["history"]),
			}
		)

	schools = []
	for slug, spec in _SCHOOLS.items():
		name = frappe.db.get_value("CRM High School", {"school_code": spec["school_code"]}, "name")
		snapshot = (
			frappe.db.get_value(
				"CRM High School Annual Snapshot",
				{"high_school": name, "verification_status": "Verified", "period_type": "Annual"},
				["name", "ne_actual", "adjusted_ne_threshold", "key_account_eligible"],
				as_dict=True,
			)
			if name
			else None
		)
		schools.append(
			{
				"slug": slug,
				"high_school": name,
				"verified_snapshot": snapshot,
				"stakeholders": frappe.db.count("CRM School Stakeholder", {"high_school": name}) if name else 0,
				"activities": frappe.db.count("CRM School Activity", {"high_school": name}) if name else 0,
			}
		)

	result = {
		"ok": all(s.get("seeded") and s.get("stage_ok") for s in students)
		and all(s["verified_snapshot"] for s in schools),
		"students": students,
		"schools": schools,
		"service_user": frappe.conf.get(SERVICE_USER_CONFIG_KEY),
	}
	print(frappe.as_json(result))
	return result
