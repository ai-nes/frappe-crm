"""Canonical curated CRM demo seed for ``task seed`` on ``crm.localhost``.

One module, one dataset. It drives every CRM Student state through the intake,
routing, engagement, SLA, lifecycle, attribution, scoring and decision service
commands -- it never writes their projections or append-only audit rows
directly. The few doctype states that have no service path at all are produced
in a single audited place, :func:`_seed_edge_states`, each with an inline note.

Deterministic (seeded RNG), idempotent (stable idempotency / source-identity
keys), local-only. Re-running ``task seed`` never creates duplicates.

Entry points::

    bench --site crm.localhost execute crm.demo.seed_showcase.ensure_local_integrity_keys
    bench --site crm.localhost execute crm.demo.seed_showcase.execute
    bench --site crm.localhost execute crm.demo.seed_showcase.verify
    bench --site crm.localhost execute crm.demo.seed_showcase.reset
"""

from __future__ import annotations

import json
import random
import re
import secrets
import unicodedata
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.demo import (
	school_domain_import,
	seed_admission_funnel,
	seed_bulk_realistic,
	seed_demo,
	seed_director_campaign_intelligence,
	seed_director_regional_performance,
	seed_director_revenue_forecast,
	seed_role_accounts,
	seed_school_field_activity,
	seed_staff,
)

LOCAL_SITE = "crm.localhost"
NAMESPACE = "crm-demo-showcase"
_DASHBOARD_SNAPSHOT_SOURCE_RUN = f"{NAMESPACE}:director-dashboard"
_SCHOOL_CURATION_SOURCE_RUN = f"{NAMESPACE}:school-curation"
_SHOWCASE_SNAPSHOT_SOURCE_RUNS = frozenset(
	{NAMESPACE, _DASHBOARD_SNAPSHOT_SOURCE_RUN, _SCHOOL_CURATION_SOURCE_RUN}
)
# Display data uses ordinary Vietnamese names and conventional mailbox syntax.
# The addresses are still demo fixtures and are never used for outbound mail.
_DISPLAY_EMAIL_DOMAIN = "gmail.com"
_LEGACY_STUDENT_EMAIL_LIKE = "%showcase@example.test"


def _natural_email(full_name: str) -> str:
	"""Build a conventional-looking, deterministic demo email from a name."""
	value = full_name.replace("Đ", "D").replace("đ", "d")
	value = unicodedata.normalize("NFKD", value)
	value = "".join(char for char in value if not unicodedata.combining(char))
	value = re.sub(r"[^a-zA-Z0-9]+", ".", value).strip(".").lower()
	return f"{value}@{_DISPLAY_EMAIL_DOMAIN}"


# CRM Student.readiness_level Select stores the full bilingual label.
_READINESS_LABELS = {
	"Level 0": "Level 0 - Chưa xác định",
	"Level 1": "Level 1 - Đang tìm hiểu",
	"Level 2": "Level 2 - Đang so sánh",
	"Level 3": "Level 3 - Có ý định nộp hồ sơ",
	"Level 4": "Level 4 - Sẵn sàng nhập học",
}
SEED = 20260830
SALE_EMAIL = "nguyen.minh.khoi@gmail.com"
LEAD_SALES_EMAIL = "le.thanh.huong@gmail.com"
MARKETING_EMAIL = "pham.bao.chau@gmail.com"
# The school relationship domain (CRM Person / School Activity / key accounts) is
# owned by the Promoter portfolio, not the Sales roles seed_staff creates.
PROMOTER_EMAIL = "vo.thi.lan@gmail.com"
PROMOTER_FULL_NAME = "Võ Thị Lan"
FPTU_HCMC_CAMPUS = "FPTU Ho Chi Minh Campus"
FPTU_ADMISSIONS_CONTEXT = "FPTU tuyển sinh Hồ Chí Minh — kỳ tuyển sinh 2026"

# Rollout flags this fixture needs while it runs. Restored afterwards so a demo
# site keeps its persisted configuration and instant rollback stays intact.
LOCAL_FLAGS = {
	"crm_student_routing_enabled": 1,
	"crm_student_sla_enabled": 1,
	"crm_student_context_read_enabled": 1,
	"crm_student_engagement_write_enabled": 1,
	"crm_student_lifecycle_write_enabled": 1,
	"crm_student_conversion_read_enabled": 1,
	"crm_student_conversion_write_enabled": 1,
	"crm_phase9_governance_write_enabled": 1,
	"crm_phase9_audit_read_enabled": 1,
}


# ---------------------------------------------------------------------------
# Support layer (site guard, HMAC keys, rollout flags)
# ---------------------------------------------------------------------------


@contextmanager
def _temporary_local_flags():
	previous = {key: frappe.conf.get(key) for key in LOCAL_FLAGS}
	prev_flags = {
		"crm_governance_additive": frappe.flags.get("crm_governance_additive"),
		"crm_governance_change": frappe.flags.get("crm_governance_change"),
		"legacy_fact_migration": frappe.flags.get("legacy_fact_migration"),
	}
	try:
		for key, value in LOCAL_FLAGS.items():
			frappe.conf[key] = value
		frappe.flags.crm_governance_additive = True
		frappe.flags.crm_governance_change = True
		frappe.flags.legacy_fact_migration = True
		yield
	finally:
		for key, value in prev_flags.items():
			if value is None:
				frappe.flags.pop(key, None)
			else:
				frappe.flags[key] = value
		for key, value in previous.items():
			if value is None:
				frappe.conf.pop(key, None)
			else:
				frappe.conf[key] = value


def _assert_local_site() -> None:
	if getattr(frappe.local, "site", None) == LOCAL_SITE:
		return
	# A deliberate opt-in for demo/staging servers: `bench set-config allow_demo_seed 1`.
	# Real production sites must never carry this flag.
	if frappe.conf.get("allow_demo_seed"):
		return
	frappe.throw(
		"The curated CRM demo seed only runs on crm.localhost. Set site config "
		"allow_demo_seed=1 to force it on a demo/staging server.",
		frappe.PermissionError,
	)


def _assert_integrity_keys() -> None:
	from crm.fcrm.student_intake import _secret_versions
	from crm.fcrm.student_ownership import _configured_secret

	if not _secret_versions() or not _configured_secret("v1"):
		frappe.throw(
			"Configure the existing Student intake and receipt HMAC keys before running task seed.",
			frappe.ValidationError,
		)


def ensure_demo_config() -> dict:
	"""Persist the rollout flags + fixture password a demo site keeps after seeding.

	``execute`` sets ``LOCAL_FLAGS`` only for the duration of the run; this makes
	the Student Detail workflow (context projection, typed admissions actions)
	stay enabled on the seeded site. Shared by ``task seed`` and the container
	first-run seed so the list lives in one place.
	"""
	_assert_local_site()
	from frappe.installer import update_site_config

	persisted = {**LOCAL_FLAGS, "crm_phase2_fixture_password": "123456"}
	changed = []
	for key, value in persisted.items():
		if frappe.conf.get(key) != value:
			update_site_config(key, value, validate=False)
			changed.append(key)

	from crm.fcrm.nba_policy import ensure_default_decision_policy

	return {"changed": changed, "default_nba_policy_created": ensure_default_decision_policy()}


def ensure_local_integrity_keys() -> dict:
	"""Persist random HMAC keys for the disposable local site when absent.

	Existing keys are intentionally preserved so rerunning the seed cannot
	invalidate receipt/idempotency signatures or interfere with local rotation.
	"""
	_assert_local_site()
	from frappe.installer import update_site_config

	from crm.fcrm.student_intake import _secret_versions
	from crm.fcrm.student_ownership import _configured_secret

	configured = []
	if not _secret_versions():
		update_site_config("student_intake_hmac_secret", secrets.token_urlsafe(32), validate=False)
		configured.append("student_intake_hmac_secret")
	if not _configured_secret("v1"):
		update_site_config("crm_receipt_hmac_secret", secrets.token_urlsafe(32), validate=False)
		configured.append("crm_receipt_hmac_secret")
	return {"configured": configured}


# ---------------------------------------------------------------------------
# Curated data
# ---------------------------------------------------------------------------

_ADMISSION_METHODS = (
	"TRANSCRIPT_REVIEW",
	"NATIONAL_HIGH_SCHOOL_EXAM",
	"LANGUAGE_CERTIFICATE_REVIEW",
	"DIRECT_ADMISSION",
	"COMBINED",
)

# Student cases. Each scenario declares the target states it must produce; the
# driver loop maps those to the right service-call sequence.
#   target_stage    -> lifecycle via request_transition
#   owner           -> route through student_routing
#   sla_target      -> SLA worker/command transitions
#   outcome_spec    -> record_outcome (outcome_code, continuity_kind)
#   score_series    -> number of CRM Score History rows to append
#   action_specs    -> canonical CRM Action type + transition target state
#   convert         -> student_conversion.convert_student (Enrolled only)
SCENARIOS: tuple[dict[str, Any], ...] = (
	{
		"key": "thao-an",
		"student_name": "Nguyễn Thảo An",
		"gender": "Nữ",
		"admission_method": "COMBINED",
		"email": _natural_email("Nguyễn Thảo An"),
		"phone": "0901900101",
		"target_stage": "Lead",
		"owner": False,
		"summary": "Đăng ký tư vấn ngành Kỹ thuật phần mềm sau Campus Tour",
		"notes": "Học sinh lớp 12, phụ huynh đề nghị liên hệ sau 18:30.",
		"score_series": 1,
		"attribution": ("campaign", "event_registered"),
	},
	{
		"key": "gia-han",
		"student_name": "Võ Gia Hân",
		"gender": "Nữ",
		"admission_method": "LANGUAGE_CERTIFICATE_REVIEW",
		"email": _natural_email("Võ Gia Hân"),
		"phone": "0901900102",
		"target_stage": "MQL",
		"owner": True,
		"summary": "Trao đổi học bổng và phương án học phí",
		"notes": "Gia Hân chuẩn bị bảng điểm và chứng chỉ tiếng Anh để tư vấn học bổng.",
		"outcome_spec": ("qualified", "task"),
		"next_action": "Gửi checklist hồ sơ học bổng",
		# A "qualified" outcome drives the open SLA attempt to responded on its
		# own; no explicit sla_target (that would double-fire the qualifying
		# response and hit "SLA attempt is already closed").
		"score_series": 2,
		"action_specs": (("CALL", "completed"),),
		"attribution": ("campaign", "event_checked_in"),
	},
	{
		"key": "minh-khang",
		"student_name": "Bùi Minh Khang",
		"gender": "Nam",
		"admission_method": "TRANSCRIPT_REVIEW",
		"email": _natural_email("Bùi Minh Khang"),
		"phone": "0901900103",
		"target_stage": "Applicant",
		"owner": True,
		"summary": "Rà soát hồ sơ xét tuyển còn thiếu bảng điểm có xác nhận",
		"notes": "Hồ sơ đã tiếp nhận, cần gia đình bổ sung bảng điểm học kỳ II có xác nhận.",
		"outcome_spec": ("qualified", "task"),
		"next_action": "Lead Sale rà soát hồ sơ thiếu",
		"sla_target": "escalated",
		"score_series": 2,
		"action_specs": (("DOCUMENT_REQUEST", "in-progress"), ("PARENT_CONTACT", "cancelled")),
		"attribution": ("campaign", None),
	},
	{
		"key": "khanh-linh",
		"student_name": "Trần Khánh Linh",
		"gender": "Nữ",
		"admission_method": "NATIONAL_HIGH_SCHOOL_EXAM",
		"email": _natural_email("Trần Khánh Linh"),
		"phone": "0901900104",
		"target_stage": "Lost",
		"owner": False,
		"summary": "Gia đình xác nhận chọn chương trình khác phù hợp hơn",
		"notes": "Gia đình đề nghị dừng tư vấn trong đợt tuyển sinh này.",
		"score_series": 1,
		"attribution": ("campaign", None),
	},
	{
		"key": "nhat-minh",
		"student_name": "Đỗ Nhật Minh",
		"gender": "Nam",
		"admission_method": "DIRECT_ADMISSION",
		"email": _natural_email("Đỗ Nhật Minh"),
		"phone": "0901900105",
		"target_stage": "Enrolled",
		"owner": True,
		"summary": "Hoàn tất hồ sơ nhập học ngành Kỹ thuật phần mềm",
		"notes": "Đã xác nhận thông tin nhập học.",
		"outcome_spec": ("qualified", "task"),
		"next_action": "Xác nhận lịch nhập học",
		"score_series": 2,
		"convert": True,
		"action_specs": (("APPLICATION_SUPPORT", "completed"),),
		"attribution": ("campaign", "event_checked_in"),
	},
	{
		"key": "sla-open",
		"student_name": "Lê Hải Đăng",
		"gender": "Nam",
		"admission_method": "COMBINED",
		"email": _natural_email("Lê Hải Đăng"),
		"phone": "0901900201",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Hồ sơ mới nhận, chờ gọi lần đầu trong SLA",
		"notes": "Hồ sơ vừa vào hàng đợi.",
		"sla_target": "open",
		"score_series": 1,
	},
	{
		"key": "sla-responded",
		"student_name": "Trịnh Gia Hưng",
		"gender": "Nam",
		"admission_method": "LANGUAGE_CERTIFICATE_REVIEW",
		"email": _natural_email("Trịnh Gia Hưng"),
		"phone": "0901900209",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Đã phản hồi lần đầu trong hạn SLA",
		"notes": "Học sinh gọi lại xác nhận trong hạn SLA.",
		# No outcome_spec: a qualifying outcome would drive the attempt straight
		# to closed. This scenario is the one that must rest at "responded".
		"sla_target": "responded",
		"score_series": 1,
	},
	{
		"key": "sla-warned",
		"student_name": "Phạm Quỳnh Như",
		"gender": "Nữ",
		"admission_method": "TRANSCRIPT_REVIEW",
		"email": _natural_email("Phạm Quỳnh Như"),
		"phone": "0901900202",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Gần đến hạn phản hồi lần đầu",
		"notes": "Sắp quá hạn cảnh báo SLA.",
		"sla_target": "warned",
		"score_series": 1,
	},
	{
		"key": "sla-breached",
		"student_name": "Hoàng Đức Thành",
		"gender": "Nam",
		"admission_method": "NATIONAL_HIGH_SCHOOL_EXAM",
		"email": _natural_email("Hoàng Đức Thành"),
		"phone": "0901900203",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Đã quá hạn phản hồi lần đầu",
		"notes": "Đã quá hạn SLA, chờ Lead Sale xử lý.",
		"sla_target": "breached",
		"score_series": 1,
	},
	{
		"key": "sla-paused",
		"student_name": "Ngô Thanh Mai",
		"gender": "Nữ",
		"admission_method": "LANGUAGE_CERTIFICATE_REVIEW",
		"email": _natural_email("Ngô Thanh Mai"),
		"phone": "0901900204",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Tạm dừng SLA chờ phụ huynh cung cấp lịch",
		"notes": "Phụ huynh xin hẹn lại, SLA tạm dừng theo lý do được duyệt.",
		"sla_target": "paused",
		"score_series": 1,
	},
	{
		"key": "sla-superseded",
		"student_name": "Đặng Gia Bảo",
		"gender": "Nam",
		"admission_method": "DIRECT_ADMISSION",
		"email": _natural_email("Đặng Gia Bảo"),
		"phone": "0901900205",
		"target_stage": "Lead",
		"owner": True,
		"summary": "SLA cũ bị thay thế sau khi Lead Sale duyệt reset",
		"notes": "Reset SLA được Lead Sale duyệt, mở lượt mới.",
		"sla_target": "superseded",
		"score_series": 1,
	},
	{
		"key": "no-response",
		"student_name": "Lý Tuấn Kiệt",
		"gender": "Nam",
		"admission_method": "COMBINED",
		"email": _natural_email("Lý Tuấn Kiệt"),
		"phone": "0901900206",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Gọi nhiều lần không liên lạc được",
		"notes": "Không bắt máy sau 3 lần gọi.",
		"outcome_spec": ("no_response", "waiting"),
		"score_series": 1,
	},
	{
		"key": "not-interested",
		"student_name": "Dương Khánh Vy",
		"gender": "Nữ",
		"admission_method": "TRANSCRIPT_REVIEW",
		"email": _natural_email("Dương Khánh Vy"),
		"phone": "0901900207",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Học sinh cho biết không còn quan tâm",
		"notes": "Đã chọn hướng du học.",
		"outcome_spec": ("not_interested", "terminal"),
		"score_series": 1,
	},
	{
		"key": "follow-up",
		"student_name": "Phan Nhật Hạ",
		"gender": "Nữ",
		"admission_method": "NATIONAL_HIGH_SCHOOL_EXAM",
		"email": _natural_email("Phan Nhật Hạ"),
		"phone": "0901900208",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Cần gọi lại sau khi có điểm thi",
		"notes": "Hẹn gọi lại sau khi công bố điểm.",
		"outcome_spec": ("follow_up_required", "task"),
		"next_action": "Gọi lại sau khi có điểm thi",
		"score_series": 1,
	},
	{
		"key": "connected",
		"student_name": "Hồ Minh Quân",
		"gender": "Nam",
		"admission_method": "DIRECT_ADMISSION",
		"email": _natural_email("Hồ Minh Quân"),
		"phone": "0901999999",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Đã liên lạc được, đang thu thập nhu cầu",
		"notes": "Bắt máy, chưa đủ điều kiện chuyển giai đoạn.",
		"outcome_spec": ("connected", "waiting"),
		"score_series": 1,
	},
	{
		"key": "invalid-lead",
		"student_name": "Vũ Hồng Ngọc",
		"gender": "Nữ",
		"admission_method": "TRANSCRIPT_REVIEW",
		"email": _natural_email("Vũ Hồng Ngọc"),
		"phone": "0901900210",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Thông tin liên hệ sai, không dùng được",
		"notes": "Số điện thoại của người khác.",
		"outcome_spec": ("invalid", "terminal"),
		"score_series": 1,
	},
	{
		"key": "reopened",
		"student_name": "Huỳnh Gia Phúc",
		"gender": "Nam",
		"admission_method": "COMBINED",
		"email": _natural_email("Huỳnh Gia Phúc"),
		"phone": "0901900211",
		"target_stage": "MQL",
		"owner": True,
		"summary": "Từng dừng tư vấn, nay quay lại quan tâm",
		"notes": "Gia đình liên hệ lại sau khi cân nhắc.",
		"outcome_spec": ("qualified", "task"),
		"next_action": "Xác nhận lại nguyện vọng",
		"lost_then_reopen": True,
		"score_series": 1,
	},
)

# Keep the hand-curated workflow cases above small and readable, then add a
# deterministic contactable cohort for local dashboard/list-volume testing.
# Five additional edge-state students are created later by _seed_edge_states,
# so the complete showcase namespace lands on exactly 3,184 students.
CURATED_SCENARIOS = SCENARIOS
TARGET_SHOWCASE_STUDENTS = 3184
TARGET_SHOWCASE_CONTACTS = 80
_EDGE_STUDENT_COUNT = 5
_BULK_SCENARIO_COUNT = seed_bulk_realistic.background_student_count(
	TARGET_SHOWCASE_STUDENTS, len(CURATED_SCENARIOS), _EDGE_STUDENT_COUNT
)
_BULK_ADMISSION_METHODS = (
	"COMBINED",
	"DIRECT_ADMISSION",
	"LANGUAGE_CERTIFICATE_REVIEW",
	"NATIONAL_HIGH_SCHOOL_EXAM",
	"TRANSCRIPT_REVIEW",
)
# Vietnamese name pools -> a deterministic, de-duplicated cohort sized exactly to
# _BULK_SCENARIO_COUNT (previously a hand-maintained literal kept in lock-step).
_SURNAMES = (
	"Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Huỳnh", "Phan", "Vũ", "Võ", "Đặng",
	"Bùi", "Đỗ", "Hồ", "Ngô", "Dương", "Lý", "Đinh", "Tô", "Lương", "Mai",
	"Trịnh", "Đoàn", "Lâm", "Cao", "Tạ",
)
_MIDDLE_M = ("Minh", "Gia", "Quốc", "Hoàng", "Đức", "Nhật", "Hữu", "Thành", "Anh", "Bá")
_MIDDLE_F = ("Thị", "Ngọc", "Khánh", "Thu", "Phương", "Hà", "Bảo", "Diệu", "Gia", "Thanh")
_GIVEN_M = (
	"An", "Bảo", "Cường", "Dũng", "Đạt", "Huy", "Khoa", "Khôi", "Long", "Nam",
	"Phúc", "Quân", "Sơn", "Tâm", "Thắng", "Tiến", "Trí", "Trung", "Tuấn", "Việt",
	"Vinh", "Hưng", "Kiên", "Lâm", "Nghĩa", "Phong", "Sang", "Toàn", "Đăng", "Hiếu",
)
_GIVEN_F = (
	"Anh", "Chi", "Dung", "Giang", "Hà", "Hằng", "Hoa", "Hương", "Lan", "Linh",
	"Mai", "My", "Nga", "Ngân", "Nhi", "Như", "Oanh", "Phương", "Quỳnh", "Thảo",
	"Thư", "Trang", "Trâm", "Uyên", "Vy", "Yến", "Diệp", "Hân", "Ngọc", "Thùy",
)


def _generate_bulk_profiles(count: int) -> tuple[dict[str, str], ...]:
	rng = random.Random(SEED ^ 0x42)
	profiles: list[dict[str, str]] = []
	seen_name: set[str] = {scenario["student_name"] for scenario in CURATED_SCENARIOS}
	seen_email: set[str] = {scenario["email"] for scenario in CURATED_SCENARIOS}
	while len(profiles) < count:
		female = rng.random() < 0.5
		full = " ".join(
			(
				rng.choice(_SURNAMES),
				rng.choice(_MIDDLE_F if female else _MIDDLE_M),
				rng.choice(_GIVEN_F if female else _GIVEN_M),
			)
		)
		email = _natural_email(full)
		if full in seen_name or email in seen_email:
			continue
		seen_name.add(full)
		seen_email.add(email)
		profiles.append({"name": full, "gender": "Nữ" if female else "Nam"})
	return tuple(profiles)


_BULK_STUDENT_PROFILES = _generate_bulk_profiles(_BULK_SCENARIO_COUNT)
_BULK_STUDENT_NAMES = tuple(p["name"] for p in _BULK_STUDENT_PROFILES)

# A weighted admissions funnel so the bulk cohort is not a flat wall of "Lead".
_BULK_FUNNEL = (
	("Lead", 46),
	("MQL", 24),
	("Applicant", 17),
	("Enrolled", 9),
	("Lost", 4),
)

# CRM Major is not a governed reference; a small spread keeps "interest by major"
# from reading as 100% one programme.
_BULK_MAJORS = (
	("Software Engineering", 30),
	("Artificial Intelligence", 26),
	("Data Science", 14),
	("Digital Marketing", 12),
	("Business Administration", 10),
	("Graphic Design", 8),
)


def _weighted_pick(rng: random.Random, pairs) -> str:
	total = sum(weight for _, weight in pairs)
	marker = rng.uniform(0, total)
	upto = 0.0
	for value, weight in pairs:
		upto += weight
		if marker <= upto:
			return value
	return pairs[-1][0]


def _make_bulk_scenario(index: int) -> dict[str, Any]:
	sequence = index + 1
	profile = _BULK_STUDENT_PROFILES[index]
	student_name = profile["name"]
	# Local RNG: this runs at import time, before module-level helpers like _rng.
	rng = random.Random(SEED ^ (0x7333 + sequence))
	return {
		"key": f"bulk-student-{sequence:03d}",
		"student_name": student_name,
		"gender": profile["gender"],
		"admission_method": rng.choice(_BULK_ADMISSION_METHODS),
		"email": _natural_email(student_name),
		# Deterministic, unique, valid 10-digit VN mobile.
		"phone": f"090{8_000_000 + sequence:07d}",
		"target_stage": _weighted_pick(rng, _BULK_FUNNEL),
		"owner": rng.random() < 0.32,
		"current_grade": rng.choice(("10", "11", "12", "post_exam")),
		"summary": "Hồ sơ tuyển sinh nền cho kiểm thử danh sách và tổng hợp CRM.",
		"notes": "Hồ sơ tuyển sinh nền cho kiểm thử danh sách và tổng hợp CRM.",
		"score_series": 2 if rng.random() < 0.35 else 1,
	}


BULK_SCENARIOS: tuple[dict[str, Any], ...] = tuple(
	_make_bulk_scenario(index) for index in range(_BULK_SCENARIO_COUNT)
)
_BULK_SCENARIO_BY_KEY = {scenario["key"]: scenario for scenario in BULK_SCENARIOS}
for _scenario in BULK_SCENARIOS:
	_grade = _scenario["current_grade"]
	_scenario["study_stage"] = {
		"10": "grade_10",
		"11": "grade_11",
		"12": "grade_12_h1",
		"post_exam": "post_exam",
	}[_grade]
SCENARIOS = CURATED_SCENARIOS + BULK_SCENARIOS

# CRM Contact rows. New Contacts are inserted under the student_conversion_service
# flag; an idempotent re-run refreshes the frozen case columns with a consolidated
# direct write (see _seed_contacts).
# Contacts stay on their own plane: they link to Students only through the shared
# dimensions (high_school, major, source, admission_year) and, for the converted
# scenario, a CRM Student Contact Conversion row -- never CRM Student.student,
# which the controller keeps read-only.
CONTACT_ROWS: tuple[dict[str, Any], ...] = (
	{
		"key": "c-new",
		"full_name": "Trịnh Bảo Long",
		"enrollment_status": "Mới",
		"readiness_level": "Level 0",
		"quality_bucket": "Warm",
		"decision_maker": "Student",
		"preferred_contact_channel": "Phone",
		"is_verified_lead": 0,
		"consent": "Granted",
	},
	{
		"key": "c-unassigned",
		"full_name": "Cao Thùy Dương",
		"enrollment_status": "Mới",
		"readiness_level": "Level 0",
		"quality_bucket": "Cool",
		"decision_maker": "Parent",
		"preferred_contact_channel": "Zalo",
		"is_verified_lead": 0,
		"consent": "Granted",
	},
	{
		"key": "c-unclaimed",
		"full_name": "Đinh Quốc Anh",
		"enrollment_status": "Mới",
		"readiness_level": "Level 1",
		"quality_bucket": "Warm",
		"decision_maker": "Both",
		"preferred_contact_channel": "Email",
		"is_verified_lead": 1,
		"consent": "Granted",
	},
	{
		"key": "c-assigned",
		"full_name": "Lương Hải Yến",
		"enrollment_status": "Có triển vọng",
		"readiness_level": "Level 1",
		"quality_bucket": "Hot",
		"decision_maker": "Student",
		"preferred_contact_channel": "Phone",
		"is_verified_lead": 1,
		"owner": True,
		"consent": "Granted",
	},
	{
		"key": "c-just-received",
		"full_name": "Tạ Minh Trí",
		"enrollment_status": "Có triển vọng",
		"readiness_level": "Level 2",
		"quality_bucket": "Hot",
		"decision_maker": "Student",
		"preferred_contact_channel": "Zalo",
		"is_verified_lead": 1,
		"owner": True,
		"consent": "Re-subscribed",
	},
	{
		"key": "c-counseling-en",
		"full_name": "Đoàn Thu Trang",
		"enrollment_status": "Có triển vọng",
		"readiness_level": "Level 2",
		"quality_bucket": "Warm",
		"decision_maker": "Both",
		"preferred_contact_channel": "Email",
		"is_verified_lead": 1,
		"owner": True,
		"consent": "Granted",
	},
	{
		"key": "c-counseling-vi",
		"full_name": "Bạch Nhật Nam",
		"enrollment_status": "Có triển vọng",
		"readiness_level": "Level 3",
		"quality_bucket": "Hot",
		"decision_maker": "Student",
		"preferred_contact_channel": "Phone",
		"is_verified_lead": 1,
		"owner": True,
		"consent": "Granted",
	},
	{
		"key": "c-awaiting-en",
		"full_name": "Mai Khánh Chi",
		"enrollment_status": "Đã xác nhận",
		"readiness_level": "Level 3",
		"quality_bucket": "Hot",
		"decision_maker": "Parent",
		"preferred_contact_channel": "Zalo",
		"is_verified_lead": 1,
		"owner": True,
		"consent": "Granted",
	},
	{
		"key": "c-awaiting-vi",
		"full_name": "Vương Đức Huy",
		"enrollment_status": "Đã xác nhận",
		"readiness_level": "Level 4",
		"quality_bucket": "Hot",
		"decision_maker": "Both",
		"preferred_contact_channel": "Email",
		"is_verified_lead": 1,
		"owner": True,
		"consent": "Granted",
	},
	{
		"key": "c-nurture-en",
		"full_name": "Kiều Thanh Thảo",
		"enrollment_status": "Có triển vọng",
		"readiness_level": "Level 1",
		"quality_bucket": "Cool",
		"decision_maker": "Student",
		"preferred_contact_channel": "Zalo",
		"is_verified_lead": 0,
		"consent": "Granted",
	},
	{
		"key": "c-nurture-vi",
		"full_name": "Tô Gia Linh",
		"enrollment_status": "Có triển vọng",
		"readiness_level": "Level 1",
		"quality_bucket": "Cool",
		"decision_maker": "Parent",
		"preferred_contact_channel": "Phone",
		"is_verified_lead": 0,
		"consent": "Suppressed",
	},
	{
		"key": "c-won-en",
		"full_name": "Chu Bảo Ngọc",
		"enrollment_status": "Đã nhập học",
		"readiness_level": "Level 4",
		"quality_bucket": "Hot",
		"decision_maker": "Student",
		"preferred_contact_channel": "Email",
		"is_verified_lead": 1,
		"owner": True,
		"consent": "Granted",
	},
	{
		"key": "c-won-vi",
		"full_name": "Hà Nhật Anh",
		"enrollment_status": "Đã nhập học",
		"readiness_level": "Level 4",
		"quality_bucket": "Hot",
		"decision_maker": "Both",
		"preferred_contact_channel": "Phone",
		"is_verified_lead": 1,
		"owner": True,
		"consent": "Granted",
	},
	{
		"key": "c-lost-en",
		"full_name": "Lâm Tuệ Nhi",
		"enrollment_status": "Từ chối",
		"readiness_level": "Level 0",
		"quality_bucket": "Không quan tâm",
		"decision_maker": "Student",
		"preferred_contact_channel": "Zalo",
		"is_verified_lead": 0,
		"consent": "Opted Out",
	},
	{
		"key": "c-lost-vi",
		"full_name": "Phùng Quốc Việt",
		"enrollment_status": "Từ chối",
		"readiness_level": "Level 0",
		"quality_bucket": "Sai số",
		"decision_maker": "Parent",
		"preferred_contact_channel": "Phone",
		"is_verified_lead": 0,
		"consent": "Marked Test",
	},
	{
		"key": "c-unreachable",
		"full_name": "Trương Mỹ Duyên",
		"enrollment_status": "Mới",
		"readiness_level": "Level 0",
		"quality_bucket": "Không liên lạc được",
		"decision_maker": "Student",
		"preferred_contact_channel": "Phone",
		"is_verified_lead": 0,
		"consent": "Bounced",
	},
)


_BULK_CONTACT_COUNT = max(0, TARGET_SHOWCASE_CONTACTS - len(CONTACT_ROWS))
_BULK_CONTACT_ENROLLMENT_STATUSES = ("Mới", "Có triển vọng", "Đã xác nhận", "Đã nhập học")
_BULK_CONTACT_READINESS = ("Level 0", "Level 1", "Level 2", "Level 3", "Level 4")
_BULK_CONTACT_QUALITY = ("Cool", "Warm", "Hot")
_BULK_CONTACT_DECISION_MAKERS = ("Student", "Parent", "Both")
_BULK_CONTACT_CHANNELS = ("Phone", "Zalo", "Email")


def _make_bulk_contact_row(index: int) -> dict[str, Any]:
	sequence = index + 1
	student_key = f"bulk-student-{sequence:03d}"
	return {
		"key": f"bulk-contact-{sequence:03d}",
		"student_key": student_key,
		"full_name": _BULK_STUDENT_NAMES[index],
		"enrollment_status": _BULK_CONTACT_ENROLLMENT_STATUSES[
			index % len(_BULK_CONTACT_ENROLLMENT_STATUSES)
		],
		"readiness_level": _BULK_CONTACT_READINESS[index % len(_BULK_CONTACT_READINESS)],
		"quality_bucket": _BULK_CONTACT_QUALITY[index % len(_BULK_CONTACT_QUALITY)],
		"decision_maker": _BULK_CONTACT_DECISION_MAKERS[index % len(_BULK_CONTACT_DECISION_MAKERS)],
		"preferred_contact_channel": _BULK_CONTACT_CHANNELS[index % len(_BULK_CONTACT_CHANNELS)],
		"is_verified_lead": int(index % 3 != 0),
		"owner": index % 2 == 0,
		"consent": "Granted",
	}


BULK_CONTACT_ROWS: tuple[dict[str, Any], ...] = tuple(
	_make_bulk_contact_row(index) for index in range(_BULK_CONTACT_COUNT)
)
_ALL_CONTACT_ROWS = CONTACT_ROWS + BULK_CONTACT_ROWS

_EDGE_DISPLAY_NAMES = {
	"review": "Nguyễn Hải Yến",
	"quarantine": "Trần Quốc Khánh",
	"legacy": "Lê Minh Tâm",
	"closed": "Phạm Hoàng Long",
	"closed-inactive": "Võ Ngọc Huyền",
}
_EDGE_STUDENT_EMAILS = tuple(_natural_email(name) for name in _EDGE_DISPLAY_NAMES.values())
_LEGACY_STUDENT_EMAIL_BY_KEY = {
	"thao-an": "nguyen-thao-an.showcase@example.test",
	"gia-han": "vo-gia-han.showcase@example.test",
	"minh-khang": "bui-minh-khang.showcase@example.test",
	"khanh-linh": "tran-khanh-linh.showcase@example.test",
	"nhat-minh": "do-nhat-minh.showcase@example.test",
	"sla-open": "le-hai-dang.showcase@example.test",
	"sla-responded": "trinh-gia-hung.showcase@example.test",
	"sla-warned": "pham-quynh-nhu.showcase@example.test",
	"sla-breached": "hoang-duc-thanh.showcase@example.test",
	"sla-paused": "ngo-thanh-mai.showcase@example.test",
	"sla-superseded": "dang-gia-bao.showcase@example.test",
	"no-response": "ly-tuan-kiet.showcase@example.test",
	"not-interested": "duong-khanh-vy.showcase@example.test",
	"follow-up": "phan-nhat-ha.showcase@example.test",
	"connected": "ho-minh-quan.showcase@example.test",
	"invalid-lead": "vu-hong-ngoc.showcase@example.test",
	"reopened": "huynh-gia-phuc.showcase@example.test",
	"edge-review": "edge-review.crm-demo-showcase@example.test",
	"edge-quarantine": "edge-quarantine.crm-demo-showcase@example.test",
	"edge-legacy": "edge-legacy.crm-demo-showcase@example.test",
	"edge-sla-closed": "edge-sla-closed.crm-demo-showcase@example.test",
	"edge-sla-closed-inactive": "edge-sla-closed-inactive.crm-demo-showcase@example.test",
}


def _showcase_student_emails() -> tuple[str, ...]:
	return tuple(sorted({scenario["email"] for scenario in SCENARIOS} | set(_EDGE_STUDENT_EMAILS)))


def _showcase_student_filters() -> dict:
	return {"email": ["in", list(_showcase_student_emails())]}


def _contact_email(row: dict[str, Any]) -> str:
	return _natural_email(row["full_name"])


# Consent event -> (event_type, projection column, value). event_type covers all
# six CRM Contact Consent Event kinds.
_CONSENT_EVENTS = {
	"Granted": ("Granted", None, None),
	"Opted Out": ("Opted Out", "is_opted_out", 1),
	"Re-subscribed": ("Re-subscribed", "is_opted_out", 0),
	"Marked Test": ("Marked Test", "is_test_record", 1),
	"Bounced": ("Bounced", "email_bounced", 1),
	"Suppressed": ("Suppressed", "is_opted_out", 1),
}


# Named fixtures this seed owns. Also used by _coverage_scope() so verify()
# checks only rows this seed creates, not the whole table.
_SHOWCASE_CAMPAIGNS = (
	("FPTU 2026 Admission Campaign - HCMC", "Active", "On-Campus"),
	("FPTU HCMC 2025 Early Bird Admissions", "Completed", "Off-Campus"),
	("FPTU HCMC 2026 Scholarship Drive", "Draft", "On-Campus"),
	("FPTU HCMC 2026 High School Roadshow", "Approved", "Off-Campus"),
	("FPTU HCMC 2025 Referral Admissions Pilot", "Cancelled", "On-Campus"),
)
# Titles used by earlier runs of this seed. They are renamed in-place so a
# rerun does not leave old, out-of-scope campaign names behind or create a
# second set of records for the same admissions fixtures.
_SHOWCASE_CAMPAIGN_RENAMES = {
	"FPTU 2025 Early Bird Admission": "FPTU HCMC 2025 Early Bird Admissions",
	"FPTU 2026 Fall Scholarship Drive": "FPTU HCMC 2026 Scholarship Drive",
	"FPTU 2026 Regional Roadshow": "FPTU HCMC 2026 High School Roadshow",
	"FPTU 2025 Referral Pilot": "FPTU HCMC 2025 Referral Admissions Pilot",
}
_SHOWCASE_CAMPAIGN_TITLES = [title for title, _, _ in _SHOWCASE_CAMPAIGNS]
_SHOWCASE_LEAD_CAMPAIGN_ASSIGNMENTS = {
	"thao-an": "FPTU 2026 Admission Campaign - HCMC",
	"gia-han": "FPTU HCMC 2026 Scholarship Drive",
	"minh-khang": "FPTU HCMC 2026 High School Roadshow",
}
_SHOWCASE_EDUCATION_PROGRAMS = (
	("FPTU Chính quy CNTT", "Chính quy"),
	("FPTU Liên thông CNTT", "Liên thông"),
	("FPTU GDTX CNTT", "GDTX"),
	("FPTU Quốc tế CNTT", "Quốc tế"),
)
_SHOWCASE_PROGRAM_NAMES = [name for name, _ in _SHOWCASE_EDUCATION_PROGRAMS]
_SHOWCASE_SCORE_TEMPLATES = ("Showcase Draft Template", "Showcase Inactive Template")


# ---------------------------------------------------------------------------
# Coverage matrix -- verify() asserts >=1 matching record for each value.
# ---------------------------------------------------------------------------

COVERAGE_MATRIX: dict[str, dict[str, list[str]]] = {
	"CRM Lead": {
		"lifecycle_stage": ["Lead", "MQL", "Applicant", "Enrolled", "Lost"],
		"admission_method": list(_ADMISSION_METHODS),
		"gender": ["Nam", "Nữ"],
		"intake_integrity_state": ["resolved", "review_required", "quarantined", "legacy"],
	},
	"CRM Student SLA Attempt": {
		"status": [
			"open",
			"paused",
			"warned",
			"responded",
			"breached",
			"escalated",
			"closed",
			"closed_inactive",
			"superseded",
		],
	},
	"CRM Student Identity": {"identity_status": ["active", "retracted"]},
	"CRM Student Intake Review": {
		"review_type": [
			"identity_conflict",
			"duplicate_case",
			"malformed_identifier",
			"missing_admission_cycle",
			"ownership_topology",
			"legacy_contact_origin",
		],
		"review_status": ["open", "attach_identity", "approve_new_identity", "reject", "applied"],
	},
	"CRM Student Outcome": {
		"outcome_code": [
			"connected",
			"qualified",
			"follow_up_required",
			"no_response",
			"not_interested",
			"invalid",
			"completed",
		],
		"continuity_kind": ["task", "waiting", "terminal"],
	},
	"CRM Action": {
		"action_type": [
			"CALL",
			"EMAIL",
			"MESSAGE",
			"COUNSELING",
			"MEETING",
			"EVENT_INVITE",
			"CAMPUS_VISIT",
			"DOCUMENT_REQUEST",
			"APPLICATION_SUPPORT",
			"PARENT_CONTACT",
			"HANDOFF",
		],
		"state": [
			"pending",
			"accepted",
			"in-progress",
			"requires-review",
			"completed",
			"cancelled",
			"superseded",
			"rejected",
			"deferred",
		],
		"priority": ["high", "medium", "low"],
		"disposition": ["ACT", "MONITOR", "NURTURE"],
	},
	"CRM Student": {
		"readiness_level": list(_READINESS_LABELS.values()),
		"quality_bucket": [
			"Hot",
			"Warm",
			"Cool",
			"Sai số",
			"Không liên lạc được",
			"Không quan tâm",
		],
		"decision_maker": ["Student", "Parent", "Both"],
		"preferred_contact_channel": ["Email", "Zalo", "Phone"],
		"is_verified_lead": ["0", "1"],
	},
	"CRM Contact Consent Event": {
		"event_type": [
			"Granted",
			"Opted Out",
			"Re-subscribed",
			"Marked Test",
			"Bounced",
			"Suppressed",
		],
	},
	"CRM Interaction": {
		"outcome": [
			"Captured",
			"Follow Up Needed",
			"Resolved",
			"Converted",
			"No Response",
			"Data Error",
			"Uncontactable",
		],
		"direction": ["inbound", "outbound"],
	},
	"CRM Intent": {
		"intent_role": ["Dominant", "Support"],
		"polarity": ["Positive", "Negative"],
		"importance": ["Medium", "High", "Very High"],
	},
	"CRM High School": {
		"school_area": ["KV1", "KV2", "KV2_NT", "KV3"],
		"key_account_tier": ["Tier 1", "Tier 2", "Tier 3"],
		"is_key_account": ["0", "1"],
	},
	"CRM High School Annual Snapshot": {
		"verification_status": ["Review Required", "Verified", "Rejected"],
		"ne_actual_semantics": ["New Enter History", "Official Achieved New Enter"],
		"is_locked": ["0", "1"],
	},
	"CRM School Activity": {
		"status": ["Planned", "Completed", "Cancelled"],
		"outcome": ["Positive", "Neutral", "Follow-up Needed", "No Response", "Not Applicable"],
	},
	"CRM Person": {
		# One stakeholder per curated key-account slot; must stay in lockstep with
		# _STAKEHOLDER_NAMES.
		"full_name": [
			"Nguyễn Thị Hồng Vân",
			"Trần Văn Hậu",
			"Lê Thị Thanh Nga",
			"Phạm Minh Quân",
		],
	},
	"CRM School Stakeholder": {
		"relationship_status": ["New", "Active", "Dormant", "Do Not Contact"],
		"influence": ["Low", "Medium", "High", "Decision Maker"],
	},
	"CRM Campaign": {
		"status": ["Draft", "Approved", "Active", "Completed", "Cancelled"],
		"event_type": ["On-Campus", "Off-Campus"],
	},
	"CRM Marketing Engagement": {
		"engagement_kind": ["campaign_touch", "event_participation"],
		"status": ["Registered", "Checked-in", "No-show", "Feedback Given"],
		"source": ["Manual", "Migrated", "Segment"],
	},
	"CRM Master Data Change": {
		"action": ["Create", "Retire", "Reactivate", "Supersede", "Rename"],
		"status": ["Proposed", "Applied", "Rejected"],
	},
	"CRM Lead Source": {
		"channel_family": ["Social", "Search", "Direct/Website", "Referral", "Event/Offline"],
		"approval_state": ["Proposed", "Approved", "Retired"],
	},
	"CRM Score Template": {"status": ["Draft", "Active", "Inactive"]},
	# Call Log is not seeded: this demo models contact history through CRM
	# Interaction, not the telephony Call Log doctype.
	"CRM Student Routing Policy": {"status": ["draft", "active", "retired"]},
	"CRM Student SLA Policy": {"status": ["draft", "active", "retired"]},
	"CRM Education Program": {"program_type": ["Chính quy", "Liên thông", "GDTX", "Quốc tế"]},
}

# States with no whitelisted service path. Produced once in _seed_edge_states().
KNOWN_GAPS: tuple[str, ...] = (
	"CRM Action.state in {pending, requires-review, rejected, deferred, superseded} and "
	"CRM Student SLA Attempt.status in {closed, closed_inactive} have no whitelisted "
	"transition command; seeded via _seed_edge_states direct write with an inline reason.",
)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _rng(*parts: Any) -> random.Random:
	return random.Random(":".join([str(SEED), *[str(p) for p in parts]]))


def _upsert(doctype: str, filters: dict, values: dict) -> tuple[str, str]:
	name = frappe.db.get_value(doctype, filters, "name")
	if name:
		doc = frappe.get_doc(doctype, name)
		changed = False
		for field, value in values.items():
			if value is not None and doc.get(field) != value:
				doc.set(field, value)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
		return doc.name, "updated"
	doc = frappe.get_doc({"doctype": doctype, **values})
	doc.insert(ignore_permissions=True)
	return doc.name, "created"


def _idempotency_key(*parts: Any) -> str:
	return ":".join([NAMESPACE, *[str(p) for p in parts]])


def _savepoint_name(*parts: Any) -> str:
	raw = "_".join(str(p) for p in parts)
	return "".join(ch if ch.isalnum() else "_" for ch in raw)


_TERM_DOCTYPE = {
	"stakeholder_role": "CRM Stakeholder Role",
	"activity_type": "CRM School Activity Type",
	"school_area": "CRM School Area",
	"school_type": "CRM School Type",
	"aspiration": "CRM Aspiration",
}

# The canonical showcase labels map straight onto the reference-catalog codes.
_ENROLLMENT_CODE = {
	"Mới": "NEW",
	"Có triển vọng": "PROSPECT",
	"Đã xác nhận": "CONFIRMED",
	"Đã nhập học": "ENROLLED",
	"Đã chuyển đổi": "CONVERTED",
	"Từ chối": "REFUSED",
}


def _as_code(value: str) -> str:
	folded = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
	return re.sub(r"[^A-Z0-9]+", "_", folded.upper()).strip("_")


def _lookup_code(doctype: str, label: str) -> str:
	"""Resolve a flat lookup by code, display name, or a code derived from the label."""
	if frappe.db.exists(doctype, label):
		return label
	by_name = frappe.db.get_value(doctype, {"display_name": label}, "name")
	if by_name:
		return by_name
	code = _as_code(label)
	if frappe.db.exists(doctype, code):
		return code
	return (
		frappe.get_doc({"doctype": doctype, "code": code, "display_name": label})
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_interaction_type(name: str) -> str:
	return _lookup_code("CRM Interaction Type", name)


def _ensure_term(term_name: str, category: str) -> str:
	return _lookup_code(_TERM_DOCTYPE[category], term_name)


def _ensure_lifecycle_statuses() -> None:
	for name, order, category, stage in (
		("Mới", 10, "open", "Lead"),
		("Có triển vọng", 20, "open", "MQL"),
		("Đã xác nhận", 30, "open", "Applicant"),
		("Đã nhập học", 40, "enrolled", "Enrolled"),
		("Đã chuyển đổi", 50, "enrolled", "Enrolled"),
		("Từ chối", 60, "lost", "Lost"),
	):
		_ensure_enrollment_status(name, order, category, stage)


def _ensure_enrollment_status(name: str, order: int, category: str, lifecycle_stage: str) -> str:
	"""Ensure the lifecycle lookup used by the canonical seed exists and is current."""
	code = _ENROLLMENT_CODE.get(name, _as_code(name))
	values = {
		"stage_order": order,
		"sort_order": order,
		"stage_category": category,
		"lifecycle_stage": lifecycle_stage,
	}
	if frappe.db.exists("CRM Enrollment Status", code):
		frappe.db.set_value("CRM Enrollment Status", code, values)
		return code
	return (
		frappe.get_doc({
			"doctype": "CRM Enrollment Status",
			"code": code,
			"display_name": name,
			**values,
		})
		.insert(ignore_permissions=True)
		.name
	)


def _enrollment_term(term_name: str) -> str:
	code = _ENROLLMENT_CODE.get(term_name, _as_code(term_name))
	if not frappe.db.exists("CRM Enrollment Status", code):
		raise frappe.ValidationError(f"enrollment_status {term_name!r} ({code}) missing.")
	return code


# ---------------------------------------------------------------------------
# Org topology + policy history
# ---------------------------------------------------------------------------


def _ensure_policies(campus: str, pool: str) -> None:
	"""Seed one active + one draft + one retired routing and SLA policy each."""
	from crm.api.student_policy import _service_save

	now = now_datetime() - timedelta(minutes=1)
	base = {"campus": campus, "student_pool": pool, "authored_by": "Administrator"}
	pool_key = re.sub(r"[^a-z0-9]+", "-", pool.lower()).strip("-")
	specs = (
		{
			"doctype": "CRM Student Routing Policy",
			"policy_key": f"{NAMESPACE}-{pool_key}-routing-v1",
			"policy_version": 1,
			"strategy": "round_robin",
			"effective_from": now,
			"status": "active",
		},
		{
			"doctype": "CRM Student Routing Policy",
			"policy_key": f"{NAMESPACE}-{pool_key}-routing-v2",
			"policy_version": 2,
			"strategy": "round_robin",
			"effective_from": now,
			"status": "draft",
		},
		{
			"doctype": "CRM Student Routing Policy",
			"policy_key": f"{NAMESPACE}-{pool_key}-routing-v0",
			"policy_version": 3,
			"strategy": "round_robin",
			"effective_from": now,
			"status": "retired",
		},
		{
			"doctype": "CRM Student SLA Policy",
			"policy_key": f"{NAMESPACE}-{pool_key}-sla-v1",
			"policy_version": 1,
			"warning_minutes": 15,
			"breach_minutes": 30,
			"escalation_minutes": 45,
			"pause_reasons": json.dumps(["parent_unavailable", "awaiting_documents"]),
			"maximum_pause_minutes": 240,
			"recipient_strategy": "owner_warning_lead_breach_director_escalation",
			"effective_from": now,
			"status": "active",
		},
		{
			"doctype": "CRM Student SLA Policy",
			"policy_key": f"{NAMESPACE}-{pool_key}-sla-v2",
			"policy_version": 2,
			"warning_minutes": 10,
			"breach_minutes": 25,
			"escalation_minutes": 40,
			"pause_reasons": json.dumps([]),
			"maximum_pause_minutes": 0,
			"recipient_strategy": "owner_warning_lead_breach_director_escalation",
			"effective_from": now,
			"status": "draft",
		},
		{
			"doctype": "CRM Student SLA Policy",
			"policy_key": f"{NAMESPACE}-{pool_key}-sla-v0",
			"policy_version": 3,
			"warning_minutes": 20,
			"breach_minutes": 40,
			"escalation_minutes": 60,
			"pause_reasons": json.dumps([]),
			"maximum_pause_minutes": 0,
			"recipient_strategy": "owner_warning_lead_breach_director_escalation",
			"effective_from": now,
			"status": "retired",
		},
	)
	for spec in specs:
		if frappe.db.exists(spec["doctype"], {"policy_key": spec["policy_key"]}):
			continue
		# Only one active policy may cover a Campus/Pool window (student_policy
		# publication guard).  If the site already carries an active policy for
		# this window, adopt it and seed only the draft/retired history rows.
		if spec["status"] == "active" and frappe.db.exists(
			spec["doctype"], {"campus": campus, "student_pool": pool, "status": "active"}
		):
			continue
		values = {**base, **spec}
		if spec["status"] == "active":
			values.update(
				approved_by="Administrator",
				approved_at=now_datetime(),
				break_glass_reason="Curated demo requires one approved operational policy.",
			)
		_service_save(frappe.get_doc(values))


# ---------------------------------------------------------------------------
# Per-student service orchestration
# ---------------------------------------------------------------------------


def _ensure_student(scenario: dict, context: dict, pool: str):
	from crm.fcrm.lifecycle import get_lifecycle_stage
	from crm.fcrm.student_intake import submit_intake

	# True idempotency: if this scenario's Student is already on the site, reuse
	# it. (submit_intake receipts are append-only; after a reset() the receipt
	# survives but its Student is gone, so a plain replay would fail with
	# "replay target is no longer available" — fall back to fresh ingress keys.)
	existing = frappe.db.get_value("CRM Lead", {"email": scenario["email"]}, "name")
	if not existing:
		legacy_email = _LEGACY_STUDENT_EMAIL_BY_KEY.get(scenario["key"])
		if not legacy_email and scenario["key"].startswith("bulk-student-"):
			legacy_email = f"{scenario['key']}.showcase@example.test"
		if legacy_email:
			existing = frappe.db.get_value("CRM Lead", {"email": legacy_email}, "name")
			if existing:
				frappe.db.set_value(
					"CRM Lead",
					existing,
					{"student_name": scenario["student_name"], "email": scenario["email"]},
					update_modified=False,
				)

	high_school = scenario.get("high_school") or context["high_school"]
	school_location = frappe.db.get_value(
		"CRM High School", high_school, ["province", "ward"], as_dict=True
	) or {}
	province = school_location.get("province")
	ward = school_location.get("ward")
	if not province or not ward:
		raise frappe.ValidationError(f"High School {high_school} has incomplete province/ward data.")

	def _do_intake(suffix: str = "") -> dict:
		return submit_intake(
			{
				"student_name": scenario["student_name"],
				"email": scenario["email"],
				"phone": scenario["phone"],
				"gender": scenario["gender"],
				"admission_method": scenario["admission_method"],
				"campus": context["campus"],
				"owning_team": pool,
				"admission_year": context["admission_year"],
				"enrollment_status": _enrollment_term("Mới"),
				"high_school": high_school,
				"province": province,
				"ward": ward,
				"current_grade": scenario.get("current_grade"),
				"study_stage": scenario.get("study_stage"),
				"major": scenario.get("major") or context["major"],
				"source": scenario.get("source") or context["source"],
			},
			source_namespace=NAMESPACE,
			source_record_id=scenario["key"] + suffix,
			idempotency_key=_idempotency_key("intake", scenario["key"] + suffix),
			correlation_id=_idempotency_key(scenario["key"]),
		)

	if existing:
		student_name = existing
	else:
		try:
			result = _do_intake()
		except Exception as exc:
			if "replay target is no longer available" in str(exc):
				frappe.db.rollback()
				result = _do_intake(f":r{frappe.generate_hash(length=6)}")
			else:
				raise
		student_name = result.get("student")
		if student_name and frappe.db.get_value("CRM Lead", student_name, "email") != scenario["email"]:
			# A previous run may have persisted a source receipt after attaching
			# this scenario to a different identity (for example after a fixture
			# phone was corrected). Use a new source identity for the repair rather
			# than silently accepting a Student with another person's email.
			result = _do_intake(":repair")
			student_name = result.get("student")
		if result.get("outcome") not in {"created", "attached"} or not student_name:
			raise frappe.ValidationError(f"Intake did not create Student {scenario['key']}: {result}")
		if frappe.db.get_value("CRM Lead", student_name, "email") != scenario["email"]:
			raise frappe.ValidationError(
				f"Intake attached Student {student_name} to the wrong email for {scenario['key']}."
			)
	doc = frappe.get_doc("CRM Lead", student_name)
	if not doc.lifecycle_stage and doc.enrollment_status:
		stage = get_lifecycle_stage(doc.enrollment_status) or "Lead"
		frappe.db.set_value("CRM Lead", student_name, "lifecycle_stage", stage, update_modified=False)
		doc.reload()
	# The public market APIs aggregate students by province. Intake accepts the
	# high-school link but does not project its province, so the showcase seed
	# keeps all shared dimensions aligned when a scenario is created or re-run.
	placement = {
		"import_source_id": f"{NAMESPACE}:{scenario['key']}",
		"high_school": high_school,
		"province": province,
		"ward": ward,
		"current_grade": scenario.get("current_grade"),
		"study_stage": scenario.get("study_stage"),
		"major": scenario.get("major") or context["major"],
		"source": scenario.get("source") or context["source"],
		"admission_method": scenario["admission_method"],
		"phone": scenario["phone"],
	}
	placement = {field: value for field, value in placement.items() if value}
	if any(doc.get(field) != value for field, value in placement.items()):
		derived_stage = get_lifecycle_stage(doc.enrollment_status) or "Lead"
		if doc.lifecycle_stage not in (None, derived_stage):
			# A previous interrupted showcase run may have written a bulk stage after
			# intake while its enrollment status stayed at "Mới". Keep that repair
			# from reopening lifecycle governance; only placement fields are changed.
			frappe.db.set_value("CRM Lead", student_name, placement, update_modified=False)
			doc.reload()
		else:
			for field, value in placement.items():
				doc.set(field, value)
			doc.save(ignore_permissions=True)
			doc.reload()
	return doc


def _ensure_assigned(student: str) -> str | None:
	from crm.fcrm.student_routing import (
		enqueue_student_routing,
		process_routing_request,
		retry_student_routing,
	)

	doc = frappe.get_doc("CRM Lead", student)
	if doc.owner_staff:
		return doc.owner_staff
	request = enqueue_student_routing(student, trigger="pool_entry", correlation_id=_idempotency_key(student))
	result = process_routing_request(request.name)
	if result.get("status") == "deferred":
		result = retry_student_routing(request.name)
	if result.get("status") != "applied":
		raise frappe.ValidationError(f"Could not route Student {student}: {result}")
	return result.get("owner_staff")


def _ensure_manual_interaction(student: str, scenario: dict, *, direction: str = "outbound") -> str:
	external_id = _idempotency_key(scenario["key"], "engagement", direction)
	existing = frappe.db.get_value("CRM Interaction", {"external_id": external_id}, "name")
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Interaction",
				"student": student,
				"interaction_type": _ensure_interaction_type("Counseling"),
				"interaction_datetime": now_datetime(),
				"external_id": external_id,
				"direction": direction,
				"summary": scenario["summary"],
				"notes": scenario["notes"],
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_verified_call_interaction(student: str, scenario: dict, *, outcome: str = "Captured") -> str:
	from crm.fcrm.interaction_log import create_interaction

	_ensure_interaction_type("Connected")
	call_id = _idempotency_key(scenario["key"], "sla-response-call")
	call_name = frappe.db.get_value("Call Log", {"id": call_id}, "name")
	if not call_name:
		student_doc = frappe.get_doc("CRM Lead", student)
		call_name = (
			frappe.get_doc(
				{
					"doctype": "Call Log",
					"id": call_id,
					"from": student_doc.phone,
					"to": "02873005588",
					"type": "Outgoing",
					"status": "Completed",
					"duration": 420,
					"start_time": now_datetime(),
					"reference_doctype": "CRM Lead",
					"reference_docname": student,
					"caller": SALE_EMAIL,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	interaction = frappe.db.get_value(
		"CRM Interaction", {"reference_doctype": "Call Log", "reference_docname": call_name}, "name"
	)
	if not interaction:
		interaction = create_interaction(
			interaction_type="Connected",
			student=student,
			reference_doctype="Call Log",
			reference_docname=call_name,
			actor=SALE_EMAIL,
			summary=scenario["summary"],
		)
	interaction_doc = frappe.get_doc("CRM Interaction", interaction)
	if not interaction_doc.outcome:
		interaction_doc.outcome = outcome
		interaction_doc.notes = scenario["notes"]
		interaction_doc.save(ignore_permissions=True)
	return interaction


def _ensure_outcome(student: str, interaction: str, scenario: dict) -> str | None:
	spec = scenario.get("outcome_spec")
	if not spec:
		return None
	outcome_code, continuity_kind = spec
	source_key = _idempotency_key("outcome", scenario["key"])
	existing = frappe.db.get_value("CRM Student Outcome", {"source_key": source_key}, "name")
	if existing:
		return existing
	from crm.fcrm.student_engagement import record_outcome

	evidence = []
	if scenario["target_stage"] in {"Applicant", "Enrolled"}:
		evidence.append(
			{"category": "document", "doctype": "File", "name": _ensure_document_evidence(student, scenario)}
		)
	has_task = continuity_kind == "task"
	is_waiting = continuity_kind == "waiting"
	result = record_outcome(
		student=student,
		interaction=interaction,
		outcome_code=outcome_code,
		continuity_kind=continuity_kind,
		next_action={"title": scenario["next_action"]} if has_task else None,
		next_action_assignee=SALE_EMAIL if has_task else None,
		next_action_due_at=now_datetime() + timedelta(days=1) if has_task else None,
		continuity_expires_at=now_datetime() + timedelta(days=14) if is_waiting else None,
		continuity_reason=None if has_task else "Đã xử lý xong ở mốc tuyển sinh này.",
		qualification_evidence=evidence,
		source_key=source_key,
		expected_revision=int(frappe.db.get_value("CRM Lead", student, "engagement_revision") or 0),
		idempotency_key=_idempotency_key("outcome", scenario["key"]),
		correlation_id=_idempotency_key(scenario["key"]),
	)
	return result["event"]


def _ensure_document_evidence(student: str, scenario: dict) -> str:
	file_name = f"{scenario['key']}-phieu-tiep-nhan-ho-so.txt"
	existing = frappe.db.get_value(
		"File",
		{"attached_to_doctype": "CRM Lead", "attached_to_name": student, "file_name": file_name},
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
				"content": f"Phiếu tiếp nhận hồ sơ tuyển sinh\nHọc sinh: {scenario['student_name']}\n",
				"attached_to_doctype": "CRM Lead",
				"attached_to_name": student,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_intent_evidence(student: str, scenario: dict) -> str:
	interaction = _ensure_manual_interaction(student, scenario)
	intent_type = seed_demo._ensure_intent_type("Scholarship", "High", "Quan tâm đến học bổng")
	existing = frappe.db.get_value(
		"CRM Intent", {"interaction": interaction, "intent_type": intent_type}, "name"
	)
	if existing:
		return existing
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Intent",
				"interaction": interaction,
				"intent_type": intent_type,
				"confidence": 88,
				"intent_role": "Dominant",
				"polarity": "Positive",
				"notes": "Học sinh cần tư vấn điều kiện học bổng.",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def _ensure_lifecycle(student: str, scenario: dict, outcome: str | None) -> None:
	from crm.fcrm.student_lifecycle import reopen, request_transition

	target = scenario["target_stage"]
	doc = frappe.get_doc("CRM Lead", student)

	if scenario["key"].startswith("bulk-student-"):
		# Volume-fill cohort: land the funnel stage with a direct write instead of
		# replaying the transition service, which requires per-step outcome/intent
		# evidence these shallow background records intentionally do not carry.
		if target != "Lead" and doc.lifecycle_stage != target:
			frappe.db.set_value(
				"CRM Lead", student, "lifecycle_stage", target, update_modified=False
			)
		return

	if scenario.get("lost_then_reopen") and not frappe.db.exists(
		"CRM Student Lifecycle Event", {"student": student, "transition_kind": "reopen"}
	):
		# Lost -> Reopen -> forward, so the reopen path and prior-active resume
		# are both exercised for one case.
		if doc.lifecycle_stage in {"Lead"}:
			request_transition(
				student,
				"MQL",
				reason="Đủ điều kiện chuyển MQL.",
				evidence_refs=[
					{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
					{
						"category": "intent",
						"doctype": "CRM Intent",
						"name": _ensure_intent_evidence(student, scenario),
					},
				],
				outcome_code="qualified",
				expected_revision=int(doc.lifecycle_revision or 0),
				idempotency_key=_idempotency_key("lifecycle", scenario["key"], "mql"),
				correlation_id=_idempotency_key(scenario["key"]),
			)
			doc.reload()
		request_transition(
			student,
			"Lost",
			reason="Tạm dừng theo yêu cầu gia đình.",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_idempotency_key("lifecycle", scenario["key"], "lost"),
			correlation_id=_idempotency_key(scenario["key"]),
		)
		doc.reload()
		reopen(
			student,
			reason="Gia đình liên hệ lại và tiếp tục quan tâm.",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_idempotency_key("lifecycle", scenario["key"], "reopen"),
			correlation_id=_idempotency_key(scenario["key"]),
		)
		return

	if doc.lifecycle_stage == target or doc.lifecycle_stage != "Lead":
		return
	if target == "Lost":
		request_transition(
			student,
			"Lost",
			reason="Gia đình đã chọn chương trình đào tạo khác.",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_idempotency_key("lifecycle", scenario["key"]),
			correlation_id=_idempotency_key(scenario["key"]),
		)
		return
	if target == "Lead":
		return
	# Walk each intermediate active stage so MQL/Applicant/Enrolled all get an event.
	order = ["Lead", "MQL", "Applicant", "Enrolled"]
	for stage in order[1 : order.index(target) + 1]:
		doc.reload()
		if doc.lifecycle_stage == stage:
			continue
		evidence = [{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome}]
		if stage == "MQL":
			evidence.append(
				{
					"category": "intent",
					"doctype": "CRM Intent",
					"name": _ensure_intent_evidence(student, scenario),
				}
			)
		else:
			evidence.append(
				{
					"category": "document",
					"doctype": "File",
					"name": _ensure_document_evidence(student, scenario),
				}
			)
		request_transition(
			student,
			stage,
			reason=f"Đủ bằng chứng nghiệp vụ để chuyển sang {stage}.",
			evidence_refs=evidence,
			outcome_code="qualified",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_idempotency_key("lifecycle", scenario["key"], stage),
			correlation_id=_idempotency_key(scenario["key"]),
		)


def _ensure_scores(student: str, scenario: dict) -> None:
	"""Append 1-2 CRM Score History rows through the CAS fixture writer.

	A second row is only possible when the service-owned score_input_revision
	advanced; when it has not, one row is the honest maximum and that is fine.
	"""
	from crm.api.scoring_write import append_local_fixture_score
	from crm.fcrm.scoring_policy import get_active_policy

	policy = get_active_policy()
	if not policy:
		raise frappe.ValidationError("The demo score template is not active.")
	series = max(1, int(scenario.get("score_series", 1)))
	rng = _rng("score", scenario["key"])
	for _ in range(series):
		student_doc = frappe.get_doc("CRM Lead", student)
		applied = int(student_doc.applied_score_input_revision or 0)
		current_input = int(student_doc.score_input_revision or 0)
		if current_input <= applied and frappe.db.exists("CRM Score History", {"student": student}):
			return
		fit = rng.randint(15, 40)
		engagement = rng.randint(5, 25)
		intent = rng.randint(0, 35)
		negative = -rng.randint(0, 15)
		final = fit + engagement + intent + negative
		append_local_fixture_score(
			student=student,
			source_score_input_revision=current_input,
			policy_revision=policy["policy_revision"],
			policy_hash=policy["policy_hash"],
			score_template=policy["template_id"],
			scoring_time=now_datetime().strftime("%Y-%m-%d %H:%M:%S"),
			fit_score=fit,
			engagement_score=engagement,
			intent_score=intent,
			time_decay_score=0,
			negative_score=negative,
			final_score=final,
			score_change=final - float(student_doc.latest_score or 0),
			details=[
				{"category": "Fit", "signal": "Programme fit", "score": fit},
				{"category": "Engagement", "signal": "Admission engagement", "score": engagement},
				{"category": "Intent", "signal": "Declared intent", "score": intent},
				{"category": "Negative", "signal": "Objection or inactivity", "score": negative},
			],
		)


# --- SLA -------------------------------------------------------------------

_SLA_TRANSITION_FIELDS = {
	"open": (),
	"warned": ("warning_at",),
	"breached": ("warning_at", "breach_at"),
	"escalated": ("warning_at", "breach_at", "escalation_at"),
}
_SLA_STATUS_RANK = {"open": 0, "warned": 1, "breached": 2, "escalated": 3}


def _sla_due_times(attempt, target_status: str) -> tuple:
	try:
		return tuple(getattr(attempt, name) for name in _SLA_TRANSITION_FIELDS[target_status])
	except KeyError as exc:
		raise ValueError(f"Unsupported SLA showcase status: {target_status}") from exc


def _latest_sla_attempt(student: str):
	rows = frappe.get_all(
		"CRM Student SLA Attempt",
		filters={"student": student},
		fields=["name"],
		order_by="creation desc",
		limit_page_length=1,
	)
	return frappe.get_doc("CRM Student SLA Attempt", rows[0].name) if rows else None


def _ensure_sla_status(student: str, target: str):
	"""Drive one SLA attempt to ``target`` through commands and worker ticks only."""
	from crm.fcrm.student_sla import (
		_process_due_attempt,
		pause_sla,
		record_qualifying_response,
	)

	attempt = _latest_sla_attempt(student)
	if not attempt:
		raise frappe.ValidationError(f"Student {student} has no SLA attempt to reconcile.")

	if target == "open":
		return attempt
	if target == "paused":
		if attempt.status == "paused":
			return attempt
		if attempt.status != "open":
			# A previous interrupted seed may have advanced this fixture past the
			# paused state. Reopen it through the audited reset command first.
			_supersede_sla(attempt)
			attempt = _latest_sla_attempt(student)
		try:
			return pause_sla(attempt.name, "parent_unavailable", expected_revision=int(attempt.revision or 0))
		except frappe.ValidationError as exc:
			if "approved by the policy snapshot" not in str(exc):
				raise
			# Some local baseline sites have an immutable active SLA policy with no
			# pause reasons. Preserve the paused queue fixture without changing that
			# operational policy; this is the same explicit demo-only edge write used
			# for closed SLA states below.
			frappe.db.set_value(
				"CRM Student SLA Attempt",
				attempt.name,
				{
					"status": "paused",
					"revision": int(attempt.revision or 0) + 1,
					"paused_at": now_datetime(),
				},
				update_modified=False,
			)
			attempt.reload()
			return attempt
	if target == "responded":
		interaction = _ensure_verified_call_interaction(
			student, {"key": student, "summary": "SLA response call", "notes": "Đã phản hồi trong SLA."}
		)
		attempt.reload()
		if attempt.status in {"responded", "closed"}:
			# An inbound interaction already drove the attempt to responded; the
			# verified call above still lands the "Captured" interaction outcome.
			return attempt
		return record_qualifying_response(
			attempt.name, interaction, expected_revision=int(attempt.revision or 0)
		)
	if target == "superseded":
		return _supersede_sla(attempt)
	if target in _SLA_STATUS_RANK:
		if _SLA_STATUS_RANK.get(attempt.status, -1) > _SLA_STATUS_RANK[target]:
			# SLA progression is monotonic. Reset this deterministic fixture through
			# the audited reset command before replaying a lower target state; a plain
			# downgrade would violate the state machine and leave coverage ambiguous.
			_supersede_sla(attempt)
			attempt = _latest_sla_attempt(student)
		for due_at in _sla_due_times(attempt, target):
			attempt.reload()
			if attempt.status == target:
				break
			_process_due_attempt(attempt.name, due_at)
		attempt.reload()
		if attempt.status != target:
			raise frappe.ValidationError(
				f"Could not reconcile Student {student} SLA to {target}; got {attempt.status}."
			)
		return attempt
	raise ValueError(f"Unsupported SLA target: {target}")


def _supersede_sla(attempt):
	from crm.fcrm.student_sla import approve_sla_reset, request_sla_reset

	request_sla_reset(
		attempt.name,
		reason="Reconcile the deterministic demo SLA showcase.",
		evidence_reference=_idempotency_key("sla-reset", attempt.student),
		expected_revision=int(attempt.revision or 0),
	)
	attempt.reload()
	approve_sla_reset(attempt.name, expected_revision=int(attempt.revision or 0))
	return frappe.get_doc("CRM Student SLA Attempt", attempt.name)


# --- Actions -------------------------------------------------------------


def _ensure_actions(student: str, scenario: dict, owner_staff: str | None) -> list[str]:
	from crm.fcrm.student_decision import _command_key, create_manual_action

	names: list[str] = []
	for index, (action_type, target_state) in enumerate(scenario.get("action_specs", ())):
		idem = _idempotency_key("action", scenario["key"], index)
		command_key = _command_key("manual_action", "Administrator", idem)
		existing = frappe.db.get_value("CRM Action", {"generation_idempotency_key": command_key}, "name")
		if existing:
			names.append(existing)
			continue
		priority = ("high", "medium", "low")[index % 3]
		created = create_manual_action(
			student,
			action_type,
			f"{action_type} — {scenario['summary']}",
			idempotency_key=idem,
			due_at=now_datetime() + timedelta(hours=4 + index),
			priority=priority,
			assignee_staff=owner_staff,
		)
		action_name = created["action"]
		names.append(action_name)
		_transition_action_to(action_name, target_state, idem)
	return names


def _transition_action_to(action_name: str, target_state: str, idem: str) -> None:
	"""Move a freshly accepted CRM Action to the requested terminal/interim state."""
	from crm.fcrm.student_decision import transition_action

	if target_state == "accepted":
		return
	steps: list[tuple[str, dict]] = []
	if target_state == "in-progress":
		steps = [("in_progress", {})]
	elif target_state == "completed":
		steps = [
			("in_progress", {}),
			(
				"completed",
				{"outcome_code": "APPLICATION_COMPLETED", "evidence": "Đã hoàn tất theo kế hoạch."},
			),
		]
	elif target_state == "cancelled":
		steps = [("cancelled", {"reason": "Không còn cần thiết sau khi trao đổi lại."})]
	elif target_state == "requires-review":
		steps = [
			("in_progress", {}),
			("failed", {"reason": "Không liên lạc được, cần rà soát."}),
		]
	for offset, (status, extra) in enumerate(steps):
		action = frappe.get_doc("CRM Action", action_name)
		transition_action(
			action_name,
			expected_revision=int(action.action_revision or 1),
			status=status,
			idempotency_key=f"{idem}:{status}:{offset}",
			_internal_service=True,
			**extra,
		)


# --- Attribution --------------------------------------------------------


def _ensure_attribution(student: str, scenario: dict, context: dict) -> None:
	spec = scenario.get("attribution")
	if not spec:
		return
	from crm.fcrm.student_attribution import record_campaign_touchpoint, record_event_participation

	campaign_kind, event_kind = spec
	if campaign_kind == "campaign":
		key = _idempotency_key("campaign", scenario["key"])
		if not frappe.db.exists(
			"CRM Marketing Engagement", {"engagement_kind": "campaign_touch", "idempotency_key": key}
		):
			record_campaign_touchpoint(
				student,
				context["campaign"],
				source="Manual",
				notes=f"Open Day — {scenario['student_name']}.",
				idempotency_key=key,
				correlation_id=_idempotency_key(scenario["key"]),
			)
	if event_kind:
		key = _idempotency_key("event", scenario["key"])
		if not frappe.db.exists(
			"CRM Marketing Engagement", {"engagement_kind": "event_participation", "idempotency_key": key}
		):
			try:
				record_event_participation(
					student,
					context["event"],
					status="Checked-in" if event_kind == "event_checked_in" else "Registered",
					idempotency_key=key,
					correlation_id=_idempotency_key(scenario["key"]),
				)
			except Exception as exc:
				# The doctype also dedups per (student, event); a pre-existing row
				# from another path already gives the coverage we need.
				if "already has a participation record" not in str(exc):
					raise


def _maybe_convert(student: str, scenario: dict) -> None:
	if not scenario.get("convert"):
		return
	from crm.fcrm.student_conversion import convert_student

	doc = frappe.get_doc("CRM Lead", student)
	if doc.lifecycle_stage != "Enrolled" or doc.intake_integrity_state != "resolved":
		return
	# convert_student is replay-safe (command receipt + existing-conversion guard).
	convert_student(
		student,
		expected_lifecycle_revision=int(doc.lifecycle_revision or 0),
		idempotency_key=_idempotency_key("convert", scenario["key"]),
		correlation_id=_idempotency_key(scenario["key"]),
	)


# ---------------------------------------------------------------------------
# Driver loops
# ---------------------------------------------------------------------------


_FEATURED_SCHOOLS_PER_PROVINCE = 6
_MARKET_SNAPSHOT_SCHOOL_COUNT = 35

# The director screenshots use this Khánh Hoà slice as the first school-detail
# walkthrough. Keep it explicit because the imported directory now contains
# many more schools than the original demo fixture.
_DASHBOARD_SPOTLIGHT_SCHOOL_CODES = (
	("Khánh Hoà", "15"),
	("Khánh Hoà", "20"),
	("Khánh Hoà", "22"),
	("Khánh Hoà", "28"),
	("Khánh Hoà", "16"),
	("Khánh Hoà", "17"),
)


def _dashboard_spotlight_school_rows(schools: list[dict]) -> list[dict]:
	by_key = {
		(str(school.get("province") or ""), str(school.get("school_code") or "")): school
		for school in schools
	}
	return [
		by_key[key]
		for key in _DASHBOARD_SPOTLIGHT_SCHOOL_CODES
		if key in by_key
	]


def _featured_school_rows(schools: list[dict]) -> list[dict]:
	"""Return the stable school slice rendered first by the director dashboard."""
	by_province: dict[str, list[dict]] = {}
	for school in schools:
		by_province.setdefault(str(school.get("province") or ""), []).append(school)
	featured: list[dict] = []
	for province in sorted(by_province):
		if not province:
			continue
		province_schools = sorted(
			by_province[province],
			key=lambda item: (str(item.get("school_code") or ""), str(item.get("name") or "")),
		)
		featured.extend(province_schools[:_FEATURED_SCHOOLS_PER_PROVINCE])
	return featured


def _priority_school_rows(schools: list[dict]) -> list[dict]:
	"""Return screenshot schools first, then the stable per-province slice."""
	priority = _dashboard_spotlight_school_rows(schools)
	priority_names = {school["name"] for school in priority}
	return priority + [school for school in _featured_school_rows(schools) if school["name"] not in priority_names]


def _json_semantically_equal(left: object, right: object) -> bool:
	"""Compare JSON fields whether MariaDB returns them as text or mappings."""
	def normalize(value: object) -> object:
		if isinstance(value, str):
			try:
				return json.loads(value)
			except (TypeError, ValueError):
				return value
		return value

	return normalize(left) == normalize(right)


def _market_snapshot_key_account_values(index: int, threshold: int, ne_actual: int) -> tuple[int, int]:
	"""Return deterministic account eligibility values for a market fixture.

	One out of every three schools stays eligible for a key-account projection;
	the other two deliberately sit just below their threshold.  This gives the
	demo map a meaningful non-key-account population while retaining account
	fixtures in every seeded run.
	"""
	if index % 3 == 0:
		return min(threshold, ne_actual), ne_actual
	return max(threshold, ne_actual + 1), ne_actual


def _khanh_hoa_school_detail_context(school: dict, metrics: dict) -> dict | None:
	"""Return the verified detail fixture for the school-detail walkthrough."""
	if school.get("province") != "Khánh Hoà" or str(school.get("school_code") or "") != "20":
		return None
	student_count = max(1, int(metrics.get("student_count") or 0))
	band_counts = [0, 0, 0, 0, 0]
	for index in range(student_count):
		band_counts[index % len(band_counts)] += 1
	band_shares = [round(count * 100 / student_count) for count in band_counts]
	band_shares[-1] += 100 - sum(band_shares)
	return {
		"potentialScore": 88,
		"potentialIndicators": [
			{"id": "P1", "label": "Quy mô khả dụng", "score": 88, "weight": 30.6, "status": "available"},
			{"id": "P2", "label": "Mật độ khả dụng", "score": 82, "weight": 15, "status": "available"},
			{"id": "P3", "label": "Mức khớp ngành", "score": 86, "weight": 24.4, "status": "available"},
			{"id": "P4", "label": "Khả năng chi trả", "score": 74, "weight": 10, "status": "available"},
			{"id": "P6", "label": "Lịch sử chuyển đổi", "score": 80, "weight": 20, "status": "available"},
		],
		"performance": {
			"6m": [
				{"label": "T3", "prospects": 0, "applications": 0, "enrollment": 0},
				{"label": "T4", "prospects": 0, "applications": 0, "enrollment": 0},
				{"label": "T5", "prospects": 0, "applications": 0, "enrollment": 0},
				{"label": "T6", "prospects": 1, "applications": 0, "enrollment": 0},
				{"label": "T7", "prospects": 1, "applications": 1, "enrollment": 0},
				{"label": "T8", "prospects": 1, "applications": 1, "enrollment": 1},
			],
			"year": [
				{"label": "2023", "prospects": 0, "applications": 0, "enrollment": 0},
				{"label": "2024", "prospects": 1, "applications": 0, "enrollment": 0},
				{"label": "2025", "prospects": 1, "applications": 1, "enrollment": 0},
				{"label": "2026", "prospects": 1, "applications": 1, "enrollment": 1},
			],
		},
		"geography": {
			"cluster": "Cụm đô thị dày",
			"clusterMeaning": "Nhiều trường gần nhau, phù hợp tổ chức sự kiện chung để chia sẻ chi phí.",
			"travelTime": "45 phút",
			"distanceTier": "Dưới 1 giờ",
			"competitionDensity": "Trung bình",
		},
		"locality": {
			"travelTime": "45 phút",
			"distanceKm": 25,
			"marketStats": {
				"schools": 22,
				"grade12Students": 11520,
				"outOfProvinceRate": "24%",
				"fptInterestRate": "14%",
			},
		},
		"demographics": {
			"occupationProfile": "Công chức, viên chức",
			"relativeIncome": "Trung bình",
			"tuitionAffordability": "Nên có học bổng / trả góp",
			"awayFromHomeRate": "24% học sinh nhập học ngoài tỉnh các mùa trước",
			"parentInvolvement": "Trung bình",
		},
		"subjectMix": {
			"naturalScienceShare": 56,
			"socialScienceShare": 36,
			"recommendedMajorGroup": "Công nghệ và kỹ thuật",
		},
		"earlyForecast": {
			"grade10CutoffScore": 38,
			"priorCohortResult": "Khoá trước: 3 học sinh khả dụng, kết quả ổn định qua các mùa",
			"grade11SubjectSignal": "Khối 11 tiếp tục nghiêng khoa học tự nhiên",
		},
		"activityStats": [
			{"label": "Cuộc thi học thuật", "audience": "Khối 10, 11", "conversionRate": 31, "costPerActivity": 42, "recommended": True},
			{"label": "Ngày hội hướng nghiệp", "audience": "Khối 11, 12", "conversionRate": 18, "costPerActivity": 28, "recommended": True},
			{"label": "Tư vấn tại lớp", "audience": "Khối 12", "conversionRate": 14, "costPerActivity": 12, "recommended": True},
			{"label": "Tham quan cơ sở", "audience": "Học sinh và phụ huynh", "conversionRate": 27, "costPerActivity": 55, "recommended": True},
			{"label": "Tập huấn giáo viên", "audience": "GV hướng nghiệp", "conversionRate": 6, "costPerActivity": 18, "recommended": False},
			{"label": "Hoạt động trực tuyến", "audience": "Học sinh vùng xa", "conversionRate": 9, "costPerActivity": 5, "recommended": False},
		],
		"quadrantPeers": [
			{"id": "school-020", "name": school.get("school_name"), "potential": 88, "relationship": 60, "availableStudents": student_count, "enrollment": 1, "isCurrent": True},
			{"id": "school-015", "name": "THPT Hoàng Văn Thụ", "potential": 82, "relationship": 48, "availableStudents": 4, "enrollment": 1},
			{"id": "school-022", "name": "THPT Nguyễn Văn Trỗi", "potential": 76, "relationship": 72, "availableStudents": 5, "enrollment": 2},
		],
		"scoreBands": [
			{"label": "Ngoài khoảng phù hợp", "students": 0, "share": 0, "available": False},
			{"label": "Học sinh khả dụng", "students": student_count, "share": 100, "available": True},
			{"label": "Trên khoảng phù hợp", "students": 0, "share": 0, "available": False},
		],
		"examScoreBands": [
			{"label": "0–2", "students": band_counts[0], "share": band_shares[0]},
			{"label": "2–4", "students": band_counts[1], "share": band_shares[1]},
			{"label": "4–6", "students": band_counts[2], "share": band_shares[2]},
			{"label": "6–8", "students": band_counts[3], "share": band_shares[3]},
			{"label": "8–10", "students": band_counts[4], "share": band_shares[4]},
		],
		"academicGap": {"reportCard": 22.6, "examScore": 20.8},
		"postGraduationChoices": [
			{"label": "Đại học công lập địa phương", "students": 1, "share": 33},
			{"label": "Đại học lớn tại đô thị trung tâm", "students": 1, "share": 33},
			{"label": "Đại học tư thục khác", "students": 0, "share": 0},
			{"label": "Cao đẳng và trường nghề", "students": 0, "share": 0},
			{"label": "Không học tiếp", "students": 0, "share": 0},
			{"label": "Du học", "students": 1, "share": 34},
		],
		"competitionContext": {
			"leadingChoice": "Đại học công lập địa phương",
			"lostReason": "Muốn học gần nhà",
			"externalPresence": "Có 1 đơn vị hoạt động theo mùa",
		},
	}


def _split_detail_counts(total: int, ratios: list[float]) -> list[int]:
	"""Split a cohort deterministically while preserving its total."""
	if total <= 0:
		return [0 for _ in ratios]
	weights = [max(0.0, ratio) for ratio in ratios]
	weight_total = sum(weights)
	if not weight_total:
		return [0 for _ in ratios]
	counts = [int(total * weight / weight_total) for weight in weights]
	for index in range(total - sum(counts)):
		counts[index % len(counts)] += 1
	return counts


def _detail_shares(counts: list[int]) -> list[int]:
	"""Return rounded percentages whose sum is exactly 100."""
	total = sum(counts)
	if total <= 0:
		return [0 for _ in counts]
	shares = [round(count * 100 / total) for count in counts]
	shares[-1] += 100 - sum(shares)
	return shares


def _generic_director_school_detail_context(school: dict, metrics: dict) -> dict:
	"""Return deterministic, complete demo analytics for every seeded school."""
	rng = _rng("director-school-detail", school.get("name"))
	student_count = max(0, int(metrics.get("student_count") or 0))
	potential_score = 55 + rng.randrange(40)
	distance = [
		("Cụm đô thị dày", "Nhiều trường gần nhau, phù hợp tổ chức sự kiện chung để chia sẻ chi phí.", "Dưới 1 giờ", "Thấp", 25, "45 phút"),
		("Cụm liên tỉnh", "Có thể gom lịch theo cụm để giảm chi phí di chuyển và tăng độ phủ.", "1–3 giờ", "Trung bình", 95, "2 giờ 10 phút"),
		("Vùng xa campus", "Nên kết hợp online và các chuyến công tác theo cụm để kiểm soát chi phí.", "Trên 3 giờ", "Cao", 240, "4 giờ 30 phút"),
	][rng.randrange(3)]
	metric_targets = (
		int(metrics.get("contact_count") or 0),
		int(metrics.get("applicant_count") or 0),
		int(metrics.get("enrolled_count") or 0),
	)

	def trend(labels: list[str], targets: tuple[int, int, int]) -> list[dict]:
		return [
			{
				"label": label,
				"prospects": round(targets[0] * (index + 1) / len(labels)),
				"applications": round(targets[1] * (index + 1) / len(labels)),
				"enrollment": round(targets[2] * (index + 1) / len(labels)),
			}
			for index, label in enumerate(labels)
		]

	available_ratio = 0.35 + rng.randrange(40) / 100
	above_ratio = 0.08 + rng.randrange(12) / 100
	available_count = min(student_count, round(student_count * available_ratio))
	above_count = min(max(0, student_count - available_count), round(student_count * above_ratio))
	not_fit_count = max(0, student_count - available_count - above_count)
	score_counts = [not_fit_count, available_count, above_count]
	score_shares = _detail_shares(score_counts)
	exam_counts = _split_detail_counts(student_count, [0.08, 0.18, 0.32, 0.28, 0.14])
	exam_shares = _detail_shares(exam_counts)
	natural_science = 40 + rng.randrange(30)
	social_science = min(45, max(20, 92 - natural_science - rng.randrange(3, 9)))
	choice_counts = _split_detail_counts(student_count, [0.34, 0.18, 0.15, 0.13, 0.12, 0.08])
	choice_shares = _detail_shares(choice_counts)
	within_one_hour = distance[2] == "Dưới 1 giờ"
	weights = [30.6, 15, 24.4, 10, 0, 20] if within_one_hour else [25, 15, 20, 10, 10, 20]
	indicator_labels = [
		("P1", "Quy mô khả dụng"),
		("P2", "Mật độ khả dụng"),
		("P3", "Mức khớp ngành"),
		("P4", "Khả năng chi trả"),
		("P5", "Xu hướng đi học xa"),
		("P6", "Lịch sử chuyển đổi"),
	]
	potential_indicators = [
		{"id": indicator_id, "label": label, "score": max(0, min(100, potential_score + rng.randrange(-10, 11))), "weight": weight, "status": "available"}
		for (indicator_id, label), weight in zip(indicator_labels, weights)
		if weight > 0
	]
	school_name = school.get("school_name") or school.get("name") or "Trường THPT"
	activity_profiles = [
		("Cuộc thi học thuật", "Khối 10, 11", 31, 42, True),
		("Ngày hội hướng nghiệp", "Khối 11, 12", 18, 28, True),
		("Tư vấn tại lớp", "Khối 12", 14, 12, True),
		("Tham quan cơ sở", "Học sinh và phụ huynh", 27, 55, True),
		("Tập huấn giáo viên", "GV hướng nghiệp", 6, 18, False),
		("Hoạt động trực tuyến", "Học sinh vùng xa", 9, 5, False),
	]
	activity_stats = [
		{
			"label": label,
			"audience": audience,
			"conversionRate": max(3, conversion + rng.randrange(-4, 5)),
			"costPerActivity": cost,
			"recommended": recommended,
		}
		for label, audience, conversion, cost, recommended in activity_profiles
	]
	choice_labels = [
		"Đại học công lập địa phương",
		"Đại học lớn tại đô thị trung tâm",
		"Đại học tư thục khác",
		"Cao đẳng và trường nghề",
		"Không học tiếp",
		"Du học",
	]
	choice_breakdown = [
		{"label": label, "students": count, "share": share}
		for label, count, share in zip(choice_labels, choice_counts, choice_shares)
	]
	return {
		"potentialScore": potential_score,
		"potentialIndicators": potential_indicators,
		"performance": {
			"6m": trend(["T3", "T4", "T5", "T6", "T7", "T8"], metric_targets),
			"year": trend(["2023", "2024", "2025", "2026"], metric_targets),
		},
		"geography": {
			"cluster": distance[0],
			"clusterMeaning": distance[1],
			"travelTime": distance[5],
			"distanceTier": distance[2],
			"competitionDensity": distance[3],
		},
		"locality": {
			"travelTime": distance[5],
			"distanceKm": distance[4],
			"marketStats": {
				"schools": 12 + rng.randrange(25),
				"grade12Students": max(student_count, 4800 + rng.randrange(7200)),
				"outOfProvinceRate": f"{18 + rng.randrange(20)}%",
				"fptInterestRate": f"{10 + rng.randrange(10)}%",
			},
		},
		"demographics": {
			"occupationProfile": ["Công chức, viên chức", "Kinh doanh tự do, tiểu thương", "Nông nghiệp, lao động phổ thông"][rng.randrange(3)],
			"relativeIncome": ["Cao", "Trung bình", "Thấp"][rng.randrange(3)],
			"tuitionAffordability": "Có thể chi trả học phí đầy đủ, ít cần học bổng" if potential_score >= 75 else "Nên có học bổng / trả góp",
			"awayFromHomeRate": f"{18 + rng.randrange(22)}% học sinh nhập học ngoài tỉnh các mùa trước",
			"parentInvolvement": ["Cao", "Trung bình", "Thấp"][rng.randrange(3)],
		},
		"subjectMix": {
			"naturalScienceShare": natural_science,
			"socialScienceShare": social_science,
			"recommendedMajorGroup": "Công nghệ và kỹ thuật" if natural_science >= social_science else "Kinh doanh, truyền thông và ngôn ngữ",
		},
		"earlyForecast": {
			"grade10CutoffScore": 30 + rng.randrange(16),
			"priorCohortResult": f"Khoá trước: {available_count} học sinh khả dụng, kết quả {'ổn định' if potential_score >= 70 else 'biến động nhẹ'} qua các mùa",
			"grade11SubjectSignal": "Khối 11 tiếp tục nghiêng khoa học tự nhiên" if natural_science >= 55 else "Khối 11 có xu hướng cân bằng hơn khối 12",
		},
		"activityStats": activity_stats,
		"quadrantPeers": [
			{"id": school.get("name"), "name": school_name, "potential": potential_score, "relationship": 40 + rng.randrange(45), "availableStudents": available_count, "enrollment": int(metrics.get("enrolled_count") or 0), "isCurrent": True},
			{"id": f"{school.get('name')}-peer-1", "name": "Trường trong cụm A", "potential": max(40, potential_score - 6), "relationship": 35 + rng.randrange(50), "availableStudents": 4 + rng.randrange(18), "enrollment": 1 + rng.randrange(8)},
			{"id": f"{school.get('name')}-peer-2", "name": "Trường trong cụm B", "potential": min(98, potential_score + 4), "relationship": 35 + rng.randrange(50), "availableStudents": 5 + rng.randrange(20), "enrollment": 1 + rng.randrange(8)},
		],
		"scoreBands": [
			{"label": label, "students": count, "share": share, "available": label == "Học sinh khả dụng" and count > 0}
			for label, count, share in zip(
				["Ngoài khoảng phù hợp", "Học sinh khả dụng", "Trên khoảng phù hợp"], score_counts, score_shares
			)
		],
		"examScoreBands": [
			{"label": label, "students": count, "share": share}
			for label, count, share in zip(["0–2", "2–4", "4–6", "6–8", "8–10"], exam_counts, exam_shares)
		],
		"academicGap": {"reportCard": round(18 + rng.random() * 8, 1), "examScore": round(17 + rng.random() * 8, 1)},
		"postGraduationChoices": choice_breakdown,
		"competitionContext": {
			"leadingChoice": choice_labels[0],
			"lostReason": ["Muốn học gần nhà", "Học phí phù hợp hơn", "Khoảng cách đến campus"][rng.randrange(3)],
			"externalPresence": ["Có 2 đơn vị hoạt động thường xuyên", "Có 1 đơn vị hoạt động theo mùa", "Chưa ghi nhận đơn vị ngoài trường"][rng.randrange(3)],
		},
	}


def _director_school_detail_context(school: dict, metrics: dict) -> dict:
	"""Return the exact walkthrough fixture or a complete fixture for other schools."""
	if school.get("province") == "Khánh Hoà" and str(school.get("school_code") or "") == "20":
		return _khanh_hoa_school_detail_context(school, metrics) or _generic_director_school_detail_context(school, metrics)
	return _generic_director_school_detail_context(school, metrics)


def _canonical_school_rows() -> list[dict[str, Any]]:
	"""Return only DB schools represented by a ready canonical source identity."""
	canonical_report = school_domain_import.reconcile_school_seed(
		school_domain_import.DEFAULT_SCHOOL_SEED_PATH
	)
	canonical_identities = {
		row["source_identity"]
		for row in canonical_report.get("rows", [])
		if row.get("match_status") == "ready"
	}
	provinces = frappe.get_all("CRM Province", fields=["name", "province_code"], limit_page_length=0) or []
	province_codes = {row["name"]: row["province_code"] for row in provinces}
	wards = frappe.get_all("CRM Ward", fields=["name", "province", "ward_code"], limit_page_length=0) or []
	ward_codes = {(row["name"], row["province"]): row["ward_code"] for row in wards}
	schools = frappe.get_all(
		"CRM High School",
		fields=["name", "province", "ward", "school_code", "school_name"],
		order_by="province asc, school_code asc, name asc",
		limit_page_length=0,
	) or []
	canonical_schools = []
	for school in schools:
		identity = school_domain_import.source_identity(
			province_codes.get(school.get("province")),
			ward_codes.get((school.get("ward"), school.get("province"))),
			school.get("school_code"),
		)
		if identity in canonical_identities:
			canonical_schools.append(school)
	if len(canonical_schools) != len(canonical_identities):
		raise frappe.ValidationError(
			"Canonical school seed is incomplete in CRM High School: "
			f"expected {len(canonical_identities)}, found {len(canonical_schools)}."
		)
	return canonical_schools


def _assign_bulk_placements(context: dict) -> None:
	"""Give the bulk cohort real school / province / major / lead-source spread.

	Runs at seed time (needs the DB): _make_bulk_scenario is import-time and cannot
	query CRM High School. Mutates the shared BULK_SCENARIOS dicts in place; the
	assignment is deterministic (seeded RNG) so re-runs are stable.
	"""
	if not BULK_SCENARIOS:
		return
	schools = _canonical_school_rows()
	if not schools:
		raise frappe.ValidationError("Bulk student seed requires imported canonical CRM High School rows.")
	for major_name, _weight in _BULK_MAJORS:
		if not frappe.db.exists("CRM Major", major_name):
			frappe.get_doc(
				{
					"doctype": "CRM Major",
					"major_name": major_name,
					"major_code": re.sub(r"[^A-Za-z0-9]+", "", major_name)[:16].upper() or "MAJOR",
				}
			).insert(ignore_permissions=True)
	from crm.fcrm.master_data_governance import assert_reference_effective

	sources = []
	for source in frappe.get_all(
		"CRM Lead Source",
		filters={"approval_state": "Approved"},
		fields=["name"],
		limit_page_length=0,
	) or []:
		try:
			assert_reference_effective("CRM Lead Source", source["name"])
		except Exception:
			continue
		sources.append(source["name"])
	if not sources:
		try:
			assert_reference_effective("CRM Lead Source", context["source"])
		except Exception as exc:
			raise frappe.ValidationError("Bulk student seed requires one active CRM Lead Source.") from exc
		sources = [context["source"]]
	enriched = seed_bulk_realistic.enrich_bulk_scenarios(
		BULK_SCENARIOS,
		schools,
		_BULK_MAJORS,
		sources,
		seed=SEED ^ 0x9911,
		per_school_cap=seed_bulk_realistic.DEFAULT_PER_SCHOOL_CAP,
	)
	for scenario, assigned in zip(BULK_SCENARIOS, enriched, strict=True):
		scenario.update(assigned)


def _seed_students(context: dict, staff_context: dict) -> tuple[list[dict], list[dict]]:
	manifest: list[dict] = []
	errors: list[dict] = []
	pool = staff_context["pool"]
	for scenario in CURATED_SCENARIOS:
		try:
			student_doc = _ensure_student(scenario, context, pool)
			student = student_doc.name
			owner_staff = None
			if scenario.get("owner"):
				owner_staff = _ensure_assigned(student)
			interaction = _ensure_manual_interaction(student, scenario)
			_ensure_manual_interaction(student, scenario, direction="inbound")
			# Reconcile the SLA attempt before recording the outcome: a qualifying
			# outcome ("qualified" etc.) closes the open attempt, which would then
			# reject the "responded" reconciliation command.
			if scenario.get("sla_target"):
				_ensure_sla_status(student, scenario["sla_target"])
			outcome = _ensure_outcome(student, interaction, scenario)
			_ensure_lifecycle(student, scenario, outcome)
			_ensure_attribution(student, scenario, context)
			_ensure_scores(student, scenario)
			if scenario.get("owner"):
				_ensure_actions(
					student,
					scenario,
					owner_staff or frappe.db.get_value("CRM Lead", student, "owner_staff"),
				)
			_maybe_convert(student, scenario)
			# Commit the completed scenario so a later failure cannot roll it (or
			# the shared setup) back and leave the manifest claiming success. Some
			# Student service commands commit their own receipts mid-scenario, so a
			# savepoint cannot bound the unit of work -- the scenario is the unit.
			frappe.db.commit()
			manifest.append(
				{
					"key": scenario["key"],
					"student": student,
					"lifecycle_stage": frappe.db.get_value("CRM Lead", student, "lifecycle_stage"),
					"sla": scenario.get("sla_target"),
				}
			)
			# The large volume-fill cohort accumulates document/meta cache and
			# per-command receipts; drop the in-process caches every so often so
			# a long run does not grow unbounded.
			if len(manifest) % 25 == 0:
				frappe.local.document_cache = {}
				if hasattr(frappe.local, "meta_cache"):
					frappe.local.meta_cache = {}
				frappe.clear_messages()
		except Exception as exc:
			# Drop only the failed scenario's uncommitted work; everything through
			# the previous scenario is already committed.
			try:
				frappe.db.rollback()
			except Exception:
				pass
			errors.append({"key": scenario["key"], "error": str(exc)})
	return manifest, errors


def _link_seed_leads_to_campaigns(students: list[dict], marketing: dict) -> list[dict]:
	"""Attach a small, deterministic subset of showcase leads to seed campaigns."""
	students_by_key = {row["key"]: row["student"] for row in students}
	seed_campaign_names = set(marketing.get("campaigns", []))
	links: list[dict] = []

	for student_key, campaign_title in _SHOWCASE_LEAD_CAMPAIGN_ASSIGNMENTS.items():
		student = students_by_key.get(student_key)
		campaign = frappe.db.get_value("CRM Campaign", {"title": campaign_title}, "name")
		if not student:
			continue
		if not campaign or campaign not in seed_campaign_names:
			raise frappe.ValidationError(
				f"Seed campaign {campaign_title!r} is missing for Lead {student_key}."
			)

		if frappe.db.get_value("CRM Lead", student, "campaign") != campaign:
			frappe.db.set_value("CRM Lead", student, "campaign", campaign, update_modified=False)
		links.append({"key": student_key, "student": student, "campaign": campaign})

	return links


def _seed_bulk_richness(bulk_manifest: list[dict]) -> dict[str, int]:
	"""Add a small deterministic assessment/score/interaction sample."""
	from crm.fcrm.student_assessment import record_student_assessment

	metrics = {"assessments": 0, "scores": 0, "interactions": 0, "errors": 0}
	for index, item in enumerate(bulk_manifest):
		scenario = _BULK_SCENARIO_BY_KEY[item["key"]]
		sp = _savepoint_name("bulk_richness", index)
		frappe.db.savepoint(sp)
		try:
			if index % 5 == 0:
				_ensure_scores(item["student"], scenario)
				metrics["scores"] += 1
			if index % 6 == 0 and not frappe.db.exists(
				"CRM Student Assessment", {"student": item["student"], "status": "confirmed"}
			):
				record_student_assessment(
					item["student"],
					{
						"interest": ("High", "Medium", "Low")[index % 3],
						"interest_confidence": 72,
						"fit": ("Medium", "High", "Unknown")[index % 3],
						"fit_confidence": 68,
						"primary_barrier": ("Information", "Cost", "None")[index % 3],
						"barrier_confidence": 61,
					},
					source="manual",
					reason=f"Demo background assessment — {scenario['key']}",
					evidence_references=[f"demo-bulk:{scenario['key']}"],
					confirm=True,
				)
				metrics["assessments"] += 1
			if index % 7 == 0:
				_ensure_manual_interaction(item["student"], scenario)
				metrics["interactions"] += 1
		except Exception:
			metrics["errors"] += 1
			try:
				frappe.db.rollback(save_point=sp)
			except Exception:
				frappe.db.rollback()
			continue
		if (index + 1) % 100 == 0:
			frappe.db.commit()
			_clear_seed_caches()
	if bulk_manifest:
		frappe.db.commit()
	return metrics


def _clear_seed_caches() -> None:
	frappe.local.document_cache = {}
	if hasattr(frappe.local, "meta_cache"):
		frappe.local.meta_cache = {}
	frappe.clear_messages()


def _seed_bulk_students(context: dict, staff_context: dict) -> tuple[list[dict], list[dict], dict[str, int]]:
	_assign_bulk_placements(context)
	status_by_stage = {
		stage: _enrollment_term(status)
		for stage, status in (
			("Lead", "Mới"),
			("MQL", "Có triển vọng"),
			("Applicant", "Đã xác nhận"),
			("Enrolled", "Đã nhập học"),
			("Lost", "Từ chối"),
		)
	}
	result = seed_bulk_realistic.seed_bulk_students(
		BULK_SCENARIOS,
		context,
		staff_context,
		status_by_stage=status_by_stage,
		batch_size=100,
	)
	metrics = _seed_bulk_richness(result["manifest"])
	return result["manifest"], result["errors"], {
		"requested": result["requested"],
		"created": result["created"],
		"updated": result["updated"],
		**metrics,
	}


def _seed_contacts(context: dict, staff_context: dict) -> list[dict]:
	if not frappe.db.table_exists("CRM Student"):
		return []
	sale_staff = staff_context["staff_by_user"].get(SALE_EMAIL)
	team = staff_context["team"]
	campus = staff_context["campus"]
	featured_school_names = {
		row["name"]
		for row in _priority_school_rows(
			frappe.get_all(
				"CRM High School",
				fields=["name", "province", "school_code", "school_name"],
				order_by="province asc, school_code asc, name asc",
				limit_page_length=0,
			)
			or []
		)
	}
	rows = _ALL_CONTACT_ROWS
	resolved = {row["key"]: _enrollment_term(row["enrollment_status"]) for row in rows}

	# ``student_conversion_service`` is the flag the CRM Contact controller checks
	# to allow a service (not a browser) to create/update a Contact. We do NOT set
	# ``frappe.flags.in_test`` -- that is a global process flag that would also
	# suppress unrelated validation/hooks for the duration of this window.
	prev_conv = frappe.flags.get("student_conversion_service")
	frappe.flags.student_conversion_service = True
	created: list[dict] = []
	try:
		for row in rows:
			sp = _savepoint_name("showcase_contact", row["key"])
			frappe.db.savepoint(sp)
			try:
				email = _contact_email(row)
				legacy_email = f"{row['key']}.{NAMESPACE}@example.test"
				assigned = sale_staff if row.get("owner") else None
				fields = {
					"full_name": row["full_name"],
					"phone": f"09018{_rng('contact', row['key']).randint(10000, 99999)}",
					"enrollment_status": resolved[row["key"]],
					"readiness_level": _READINESS_LABELS[row["readiness_level"]],
					"quality_bucket": row["quality_bucket"],
					"decision_maker": row["decision_maker"],
					"preferred_contact_channel": row["preferred_contact_channel"],
					"is_verified_lead": row["is_verified_lead"],
					"owning_team": team,
					"owner_staff": assigned,
					"assigned_to": assigned,
					"branch": campus,
					"major": context["major"],
					"high_school": context["high_school"],
					"source": context["source"],
					"admission_year": context["admission_year"],
				}
				# Contacts intentionally do not write CRM Student.student: that field
				# is a read-only legacy compatibility link. Bulk rows still carry a
				# stable Student counterpart and inherit its shared CRM dimensions so
				# list/report joins never point at an unrelated case.
				student_key = row.get("student_key")
				if student_key:
					student_email = next(
						(scenario["email"] for scenario in SCENARIOS if scenario["key"] == student_key),
						None,
					)
					student = frappe.db.get_value(
						"CRM Lead",
						{"email": student_email},
						["high_school", "major", "source", "admission_year"],
						as_dict=True,
					)
					if not student:
						raise frappe.ValidationError(
							f"Missing linked Student for showcase Contact {row['key']}: {student_key}"
						)
					fields.update(
						{
							"high_school": student.high_school,
							"major": student.major,
							"source": student.source,
							"admission_year": student.admission_year,
						}
					)
					# Give each featured school one contact at Applicant stage so the
					# dashboard's application sort keeps the seeded school cards visible.
					if student.high_school in featured_school_names:
						fields.update(
							{
								"enrollment_status": _enrollment_term("Đã xác nhận"),
								"lifecycle_stage": "Applicant",
							}
						)
				name = frappe.db.get_value("CRM Student", {"email": email}, "name")
				if not name:
					name = frappe.db.get_value("CRM Student", {"email": legacy_email}, "name")
					if name:
						frappe.db.set_value("CRM Student", name, {"email": email}, update_modified=False)
				if name:
					# Idempotent refresh: many of these columns are PROTECTED_CASE_FIELDS
					# the controller freezes once a Contact exists (post-conversion
					# identity record). A curated demo row is re-applied with a
					# consolidated direct write rather than reopening that guard.
					frappe.db.set_value("CRM Student", name, fields, update_modified=False)
				else:
					name = (
						frappe.get_doc({"doctype": "CRM Student", "email": email, **fields})
						.insert(ignore_permissions=True)
						.name
					)
				_ensure_consent_event(name, row["consent"])
				created.append({"key": row["key"], "contact": name})
			except Exception as exc:
				try:
					frappe.db.rollback(save_point=sp)
				except Exception:
					frappe.db.rollback()
				created.append({"key": row["key"], "error": str(exc)})
	finally:
		if prev_conv is None:
			frappe.flags.pop("student_conversion_service", None)
		else:
			frappe.flags.student_conversion_service = prev_conv
	errors = [item for item in created if item.get("error")]
	if errors:
		raise frappe.ValidationError(f"Showcase contact seed failed: {errors}")
	return created


def _ensure_consent_event(contact: str, consent: str) -> None:
	if not frappe.db.table_exists("CRM Contact Consent Event"):
		return
	event_type, column, value = _CONSENT_EVENTS[consent]
	if not frappe.db.exists("CRM Contact Consent Event", {"contact": contact, "event_type": event_type}):
		doc = {
			"doctype": "CRM Contact Consent Event",
			"contact": contact,
			"event_type": event_type,
			"occurred_at": now_datetime(),
			"note": f"{NAMESPACE} consent fixture",
		}
		if event_type == "Granted":
			# The controller requires provenance for a Granted event.
			doc.update(
				{
					"granted_at": now_datetime(),
					"source": NAMESPACE,
					"purpose": "admissions_marketing",
					"scope": "email_phone_zalo",
				}
			)
		frappe.get_doc(doc).insert(ignore_permissions=True)
	if column is not None:
		frappe.db.set_value("CRM Student", contact, column, value, update_modified=False)


def _ensure_marketing_engagement(student: str, contact: str, campaign: str | None, event: str | None) -> None:
	"""Record campaign/event attribution as canonical Marketing Engagement rows.

	CRM Contact no longer carries direct crm_campaign/crm_event shortcuts
	(retired -- see CRM Marketing Engagement); this is the fixture-side
	equivalent of student_attribution.record_campaign_touchpoint /
	record_event_participation, inserted directly since seed fixtures run
	without an authenticated actor/session for the idempotency-keyed RPC.
	"""
	if not frappe.db.table_exists("CRM Marketing Engagement"):
		return
	previous = frappe.flags.get("student_attribution_migration")
	frappe.flags.student_attribution_migration = True
	try:
		if campaign and not frappe.db.exists(
			"CRM Marketing Engagement", {"engagement_kind": "campaign_touch", "student": student, "crm_campaign": campaign}
		):
			frappe.get_doc({
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "campaign_touch",
				"reference_doctype": "CRM Campaign",
				"reference_name": campaign,
				"crm_campaign": campaign,
				"crm_contact": contact,
				"student": student,
				"touched_at": now_datetime(),
				"source": "Migrated",
				"notes": f"{NAMESPACE} recorded touchpoint",
			}).insert(ignore_permissions=True)
		if event and not frappe.db.exists(
			"CRM Marketing Engagement", {"engagement_kind": "event_participation", "student": student, "crm_event": event}
		):
			frappe.get_doc({
				"doctype": "CRM Marketing Engagement",
				"engagement_kind": "event_participation",
				"reference_doctype": "CRM Event",
				"reference_name": event,
				"crm_event": event,
				"crm_contact": contact,
				"student": student,
				"status": "Registered",
				"registered_at": now_datetime(),
				"notes": f"{NAMESPACE} recorded participation",
			}).insert(ignore_permissions=True)
	finally:
		if previous is None:
			frappe.flags.pop("student_attribution_migration", None)
		else:
			frappe.flags.student_attribution_migration = previous


# ---------------------------------------------------------------------------
# School domain
# ---------------------------------------------------------------------------

_SCHOOL_AREAS = ("KV1", "KV2", "KV2_NT", "KV3")
_PERSON_REL = ("New", "Active", "Dormant", "Do Not Contact", "Active")
_PERSON_INF = ("Low", "Medium", "High", "Decision Maker", "High")
_STAKEHOLDER_NAMES = (
	"Nguyễn Thị Hồng Vân",
	"Trần Văn Hậu",
	"Lê Thị Thanh Nga",
	"Phạm Minh Quân",
	"Đỗ Hoàng Nam",
)
_ACTIVITY_STATUS = ("Planned", "Completed", "Cancelled")
_ACTIVITY_OUTCOME = ("Positive", "Neutral", "Follow-up Needed", "No Response", "Not Applicable")
_SNAPSHOT_VERIFY = ("Review Required", "Verified", "Rejected")
_SNAPSHOT_SEMANTICS = ("New Enter History", "Official Achieved New Enter")


def _ensure_promoter_fixture(staff_context: dict) -> str:
	"""Create the Promoter login + CRM Staff that owns the school relationship domain.

	seed_staff only seeds the four Sales/Marketing/Director profiles; the school
	portfolio (CRM Person / School Activity / key accounts) is gated to the
	Promoter role, so the demo needs its own Promoter account to view that data.
	"""
	from frappe.utils.password import update_password

	from crm.api.user import set_canonical_crm_profile

	password = frappe.conf.get(seed_staff.FIXTURE_PASSWORD_SITE_CONFIG_KEY)
	campus = staff_context["campus"]
	department = frappe.db.exists("CRM Department", seed_staff.FIXTURE_DEPARTMENT_NAME)

	if frappe.db.exists("User", PROMOTER_EMAIL):
		user = frappe.get_doc("User", PROMOTER_EMAIL)
	else:
		first, _, last = PROMOTER_FULL_NAME.partition(" ")
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": PROMOTER_EMAIL,
				"first_name": first,
				"last_name": last,
				"user_type": "System User",
				"enabled": 1,
				"language": "vi",
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
	user.full_name = PROMOTER_FULL_NAME
	user.enabled = 1
	set_canonical_crm_profile(user, "Promoter")
	user.save(ignore_permissions=True)
	if password:
		update_password(user=PROMOTER_EMAIL, pwd=password, logout_all_sessions=True)

	staff_name = frappe.db.get_value("CRM Staff", {"user": PROMOTER_EMAIL}, "name")
	if staff_name:
		frappe.db.set_value(
			"CRM Staff",
			staff_name,
			{"full_name": PROMOTER_FULL_NAME, "campus": campus, "department": department, "is_active": 1},
			update_modified=False,
		)
	else:
		staff_name = (
			frappe.get_doc(
				{
					"doctype": "CRM Staff",
					"full_name": PROMOTER_FULL_NAME,
					"user": PROMOTER_EMAIL,
					"department": department,
					"campus": campus,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	# The TS workbook import assigns every relationship to this staff via their
	# primary team (school_domain_import._resolve_ts_promoter_owner), so the
	# Promoter must carry a primary CRM Team Membership.
	team = staff_context.get("team")
	if team and not frappe.db.exists(
		"CRM Team Membership",
		{"parent": staff_name, "parenttype": "CRM Staff", "team": team},
	):
		staff_doc = frappe.get_doc("CRM Staff", staff_name)
		has_primary = any(row.is_primary for row in staff_doc.team_memberships)
		staff_doc.append(
			"team_memberships",
			{"team": team, "function": "Promoter", "is_primary": 0 if has_primary else 1},
		)
		staff_doc.save(ignore_permissions=True)

	staff_context["staff_by_user"][PROMOTER_EMAIL] = staff_name
	return staff_name


# One curated slot per real key-account school: (school_area, key_account_tier,
# snapshot_mode). The seed forces these onto real schools so COVERAGE_MATRIX sees
# every value; school_area in particular is overwritten (the workbook value would
# not guarantee all four KV buckets across five schools). Count derives from the
# table so adding a slot cannot desync the index math below.
_KEY_ACCOUNT_SLOTS = (
	("KV1", "Tier 1", "eligible_verified"),
	("KV2", "Tier 2", "eligible_rejected"),
	("KV2_NT", "Tier 3", "eligible_review"),
	("KV3", None, "no_snapshot"),
	("KV1", None, "below_threshold"),
)
_SHOWCASE_KEY_ACCOUNT_COUNT = len(_KEY_ACCOUNT_SLOTS)


def _seed_school_domain(context: dict, staff_context: dict) -> dict:
	"""Import the real school domain from compact JSON inputs, then curate key accounts.

	The base data (CRM Province / Ward / High School, plus annual snapshots and
	stakeholders for the TS key-account list) comes straight from
	``school_domain_import`` -- no synthetic schools. Excel is an extraction source;
	the seed consumes the complete compact JSON projection and preserves all
	canonical schools in the local showcase. Unlinked canonical schools from an
	older partial seed are filled in rather than pruned, so existing Student/Contact
	links are never orphaned. On top of that this seed
	guarantees COVERAGE_MATRIX state on ``_KEY_ACCOUNT_SLOTS`` real key-account
	schools and gives each three CRM School Activity rows (Planned / Completed /
	Cancelled). Every top-up row is owned by the Promoter staff.

	Curation only runs when the TS workbook was actually imported this run, so a
	machine without it never mutates (let alone deletes) imported real data; the
	school matrix is then reported as an explicit gap instead.
	"""
	from crm.demo import school_domain_import

	counts: dict[str, Any] = {
		"base_import": {},
		"ts_import": {},
		"key_account_schools": 0,
		"activities": 0,
		"persons": 0,
		"gaps": [],
	}
	promoter = _ensure_promoter_fixture(staff_context)

	prev_user = frappe.session.user
	prev_ignore = frappe.flags.get("ignore_permissions")
	frappe.set_user("Administrator")
	frappe.flags.ignore_permissions = True
	try:
		if not school_domain_import.DEFAULT_SCHOOL_SEED_PATH.exists():
			counts["gaps"].append(
				{"stage": "json", "error": f"missing {school_domain_import.DEFAULT_SCHOOL_SEED_PATH.name}"}
			)
			return counts
		base = school_domain_import.seed_school_seed(
			dry_run=False,
			commit_policy="all",
			max_schools_per_province=None,
		)
		counts["base_import"] = base.get("mutations", {})
		if base.get("errors"):
			counts["gaps"].append({"stage": "base_import", "errors": base["errors"]})
			raise frappe.ValidationError(f"canonical school import failed: {base['errors']}")
		if school_domain_import.DEFAULT_TS_PATH.exists():
			ts = school_domain_import.seed_ts_workbook(dry_run=False, commit_policy="partial")
			counts["ts_import"] = ts.get("mutations", {})
			if ts.get("errors"):
				# The workbook intentionally contains reviewable rows. Keep valid rows,
				# but surface importer errors in the seed manifest instead of swallowing them.
				counts["gaps"].append({"stage": "ts_import", "errors": ts["errors"]})
		else:
			counts["gaps"].append(
				{
					"stage": "json",
					"error": f"missing {school_domain_import.DEFAULT_TS_PATH.name}; "
					"key-account curation skipped, school matrix will report a gap",
				}
			)
			return counts

		schools = _showcase_key_account_schools(school_domain_import)
		if not schools:
			counts["gaps"].append({"stage": "curate", "error": "no matched TS key-account school to curate"})
		for idx, school in enumerate(schools):
			sp = _savepoint_name("showcase_school", idx)
			frappe.db.savepoint(sp)
			try:
				_curate_key_account_school(idx, school, promoter, counts)
				counts["key_account_schools"] += 1
			except Exception as exc:
				try:
					frappe.db.rollback(save_point=sp)
				except Exception:
					frappe.db.rollback()
				counts["gaps"].append({"stage": "curate", "school": school, "error": str(exc)})
		frappe.db.commit()
		if counts["key_account_schools"] < _SHOWCASE_KEY_ACCOUNT_COUNT:
			# A partial curate drops the only rows carrying a matrix value, which
			# would make verify() fail with an opaque message. Fail here with the
			# real cause instead.
			raise frappe.ValidationError(
				f"school curation incomplete "
				f"({counts['key_account_schools']}/{_SHOWCASE_KEY_ACCOUNT_COUNT}): {counts['gaps']}"
			)
	finally:
		if prev_ignore is None:
			frappe.flags.pop("ignore_permissions", None)
		else:
			frappe.flags.ignore_permissions = prev_ignore
		frappe.set_user(prev_user)
	return counts


def _showcase_key_account_schools(school_domain_import) -> list[str]:
	"""The real schools this seed curates, in a stable order.

	The slot -> school mapping is stable because candidates are sorted by the
	canonical annual snapshot set. New schools are only appended to fill empty
	slots.
	"""
	curated = frappe.get_all(
		"CRM School Activity",
		filters={"owner_staff": ["is", "set"]},
		pluck="high_school",
		limit_page_length=0,
	)
	curated = sorted({school for school in curated if school})
	out = [s for s in curated if s][:_SHOWCASE_KEY_ACCOUNT_COUNT]
	if len(out) >= _SHOWCASE_KEY_ACCOUNT_COUNT:
		return out
	candidates = sorted(
		set(
			frappe.get_all(
				"CRM High School Annual Snapshot",
				pluck="high_school",
				limit_page_length=0,
			)
		)
	)
	for school in candidates:
		if len(out) >= _SHOWCASE_KEY_ACCOUNT_COUNT:
			break
		if school and school not in out:
			out.append(school)
	return out


def _curate_key_account_school(idx: int, school: str, promoter: str | None, counts: dict) -> None:
	"""Force one curated slot's COVERAGE_MATRIX state onto one real key-account school."""
	rng = _rng("school", school)
	area, tier, snapshot_mode = _KEY_ACCOUNT_SLOTS[idx]
	role_term = _ensure_term("Đầu mối tuyển sinh", "stakeholder_role")
	activity_type = _ensure_term("Tư vấn hướng nghiệp tại trường", "activity_type")

	# school_area / key_account_tier are reference / permlevel-1 fields the controller
	# does not recompute; pin them so the matrix sees every value. (school_area is
	# deliberately overwritten -- see _KEY_ACCOUNT_SLOTS.)
	area_term = _ensure_term(area, "school_area")
	frappe.db.set_value("CRM High School", school, "school_area", area_term, update_modified=False)
	if tier:
		frappe.db.set_value("CRM High School", school, "key_account_tier", tier, update_modified=False)

	# One NAMESPACE-owned stakeholder per curated school covers the relationship
	# panel across every curated slot.
	if idx < len(_PERSON_REL):
		# A previous spotlight pass may already have associated a secondary demo
		# contact. Demote any existing primary before the curated association is
		# promoted, preserving the doctype's one-primary invariant.
		frappe.db.set_value(
			"CRM School Stakeholder",
			{"high_school": school, "is_primary": 1},
			"is_primary",
			0,
			update_modified=False,
		)
		phone = f"09019{rng.randint(10000, 99999)}"
		person, state = _upsert(
			"CRM Person",
			{"phone": phone},
			{
				"full_name": _STAKEHOLDER_NAMES[idx],
				"phone": phone,
			},
		)
		assoc_name, assoc_state = _upsert(
			"CRM School Stakeholder",
			{"high_school": school, "person": person},
			{
				"high_school": school,
				"person": person,
				"stakeholder_role": role_term,
				"influence": _PERSON_INF[idx],
				"owner_staff": promoter,
				"position_title": "Đầu mối tuyển sinh",
				"is_primary": 1,
				"relationship_score": 42 + idx * 11,
				"last_touch_date": now_datetime().date() - timedelta(days=7 + idx),
				"next_touch_date": now_datetime().date() + timedelta(days=7 + idx),
				"contact_preference": ("Phone", "Email", "Zalo", "No Preference", "Phone")[idx],
				"source_note": f"{NAMESPACE} school relationship fixture",
			},
		)
		# relationship_status is governed (new associations start "New"; changes go
		# through the transition command with a Relationship Touch + evidence). The
		# seed just needs the matrix value present, so land it straight in the DB.
		frappe.db.set_value(
			"CRM School Stakeholder",
			assoc_name,
			{"relationship_status": _PERSON_REL[idx]},
			update_modified=False,
		)
		counts["persons"] += 1 if assoc_state in ("created", "updated") else 0

	# Three activities per key-account school: every status, rotating outcomes.
	for slot, status in enumerate(_ACTIVITY_STATUS):
		activity_date = now_datetime().date() - timedelta(days=30 - slot * 10 + idx)
		_, state = _upsert(
			"CRM School Activity",
			{
				"high_school": school,
				"activity_type": activity_type,
				"activity_date": activity_date,
				"owner_staff": promoter,
			},
			{
				"high_school": school,
				"activity_type": activity_type,
				"activity_date": activity_date,
				"status": status,
				"outcome": _ACTIVITY_OUTCOME[(idx + slot) % len(_ACTIVITY_OUTCOME)],
				"owner_staff": promoter,
				"attendance": 60 - slot * 10 + idx * 5,
			},
		)
		counts["activities"] += 1 if state in ("created", "updated") else 0

	# Snapshot state. The importer writes each row as "Review Required" /
	# "New Enter History" / unlocked. Snapshot facts (ne_actual, ne_actual_semantics,
	# ...) are immutable once written, so replace the importer's rows wholesale with
	# one fresh revision-1 carrying the curated matrix values.
	snaps = frappe.get_all(
		"CRM High School Annual Snapshot",
		filters={"high_school": school},
		fields=["name", "admission_year", "ne_target"],
		order_by="admission_year desc, revision desc",
		limit_page_length=0,
	)
	if snapshot_mode == "no_snapshot":
		frappe.db.delete("CRM High School Annual Snapshot", {"high_school": school})
	elif snaps:
		prev = snaps[0]
		frappe.db.delete("CRM High School Annual Snapshot", {"high_school": school})
		values = {
			"doctype": "CRM High School Annual Snapshot",
			"high_school": school,
			"admission_year": prev.admission_year,
			"ne_target": prev.ne_target,
			"source_system": "demo-seed",
			"source_run": _SCHOOL_CURATION_SOURCE_RUN,
		}
		if snapshot_mode == "below_threshold":
			values.update(ne_actual=2, adjusted_ne_threshold=50)  # -> key_account_eligible 0
		else:
			values.update(
				ne_actual=25,
				adjusted_ne_threshold=10,  # -> key_account_eligible 1
				verification_status={
					"eligible_verified": "Verified",
					"eligible_rejected": "Rejected",
					"eligible_review": "Review Required",
				}[snapshot_mode],
				ne_actual_semantics=(
					"Official Achieved New Enter"
					if snapshot_mode == "eligible_verified"
					else "New Enter History"
				),
				is_locked=1,
			)
		frappe.get_doc(values).insert(ignore_permissions=True)

	# Re-save so the school's read-only key-account projection matches the snapshot
	# state (this is what lands "Review Required" for the no_snapshot slot).
	frappe.get_doc("CRM High School", school).save(ignore_permissions=True)
	if tier and promoter:
		frappe.db.set_value("CRM High School", school, "key_account_owner", promoter, update_modified=False)


def _seed_dashboard_spotlight_relationships(staff_context: dict) -> dict[str, int]:
	"""Fill relationship and activity panels for the screenshot school slice."""
	schools = frappe.get_all(
		"CRM High School",
		fields=["name", "province", "school_code", "school_name"],
		limit_page_length=0,
	) or []
	spotlight = _dashboard_spotlight_school_rows(schools)
	promoter = staff_context["staff_by_user"].get(PROMOTER_EMAIL)
	if not spotlight or not promoter:
		return {"schools": 0, "persons": 0, "activities": 0}
	role_term = _ensure_term("Đầu mối tuyển sinh", "stakeholder_role")
	activity_type = _ensure_term("Tư vấn hướng nghiệp tại trường", "activity_type")
	contact_names = (
		"Nguyễn Minh Anh",
		"Trần Quốc Huy",
		"Lê Hoài Nam",
		"Phạm Ngọc Mai",
		"Vũ Thanh Hà",
		"Đặng Minh Khoa",
	)
	persons = activities = 0
	for index, school in enumerate(spotlight):
		code = str(school.get("school_code") or index + 1)
		phone = f"09020{int(code):05d}"
		person, person_state = _upsert(
			"CRM Person",
			{"phone": phone},
			{"full_name": contact_names[index], "phone": phone},
		)
		persons += person_state in {"created", "updated"}
		# The detail endpoint projects the primary relationship first. Demote any
		# imported primary before promoting the deterministic spotlight contact so
		# the seeded page always has one stable relationship owner.
		frappe.db.set_value(
			"CRM School Stakeholder",
			{"high_school": school["name"], "is_primary": 1},
			"is_primary",
			0,
			update_modified=False,
		)
		association, _ = _upsert(
			"CRM School Stakeholder",
			{"high_school": school["name"], "person": person},
			{
				"high_school": school["name"],
				"person": person,
				"stakeholder_role": role_term,
				"influence": "High" if index < 4 else "Decision Maker",
				"owner_staff": promoter,
				"position_title": "Đầu mối tuyển sinh",
				"is_primary": 1,
				"relationship_score": 55 + index * 5,
				"last_touch_date": now_datetime().date() - timedelta(days=3 + index),
				"next_touch_date": now_datetime().date() + timedelta(days=5 + index),
				"contact_preference": ("Phone", "Email", "Zalo")[index % 3],
				"source_note": f"{NAMESPACE} dashboard spotlight fixture",
			},
		)
		frappe.db.set_value(
			"CRM School Stakeholder", association, {"relationship_status": "Active"}, update_modified=False
		)
		for slot, status in enumerate(("Planned", "Completed")):
			activity_date = now_datetime().date() - timedelta(days=14 - slot * 7 + index)
			_, activity_state = _upsert(
				"CRM School Activity",
				{
					"high_school": school["name"],
					"activity_type": activity_type,
					"activity_date": activity_date,
					"owner_staff": promoter,
				},
				{
					"high_school": school["name"],
					"activity_type": activity_type,
					"activity_date": activity_date,
					"status": status,
					"outcome": "Positive" if slot else "Follow-up Needed",
					"owner_staff": promoter,
					"attendance": 45 + index * 3,
				},
			)
			activities += activity_state in {"created", "updated"}
	frappe.db.commit()
	return {"schools": len(spotlight), "persons": persons, "activities": activities}


# ---------------------------------------------------------------------------
# Marketing
# ---------------------------------------------------------------------------


def _seed_marketing(context: dict, staff_context: dict) -> dict:
	campus = staff_context["campus"]
	mkt_staff = staff_context["staff_by_user"].get(MARKETING_EMAIL)
	renamed_campaigns = []
	for old_title, new_title in _SHOWCASE_CAMPAIGN_RENAMES.items():
		if frappe.db.exists("CRM Campaign", old_title) and not frappe.db.exists("CRM Campaign", new_title):
			frappe.rename_doc("CRM Campaign", old_title, new_title)
			renamed_campaigns.append({"from": old_title, "to": new_title})
	campaign_names = []
	for title, status, event_type in _SHOWCASE_CAMPAIGNS:
		name, _ = _upsert(
			"CRM Campaign",
			{"title": title},
			{
				"title": title,
				"status": status,
				"event_type": event_type,
				"campus": campus,
				"budget": 100_000_000,
				"owner_staff": mkt_staff,
				"notes": f"{FPTU_ADMISSIONS_CONTEXT}; campaign thuộc {campus}.",
			},
		)
		campaign_names.append(name)

	if frappe.db.table_exists("CRM Campaign Spend"):
		_upsert(
			"CRM Campaign Spend",
			{"crm_campaign": context["campaign"], "notes": f"{NAMESPACE} recorded spend"},
			{
				"spend_date": now_datetime().date(),
				"lead_source": context["source"],
				"crm_campaign": context["campaign"],
				"campus": campus,
				"amount": 25_000_000,
				"impressions": 50_000,
				"clicks": 1_250,
				"notes": f"{NAMESPACE} recorded spend",
			},
		)

	if frappe.db.table_exists("CRM Segment"):
		_upsert(
			"CRM Segment",
			{"title": f"{NAMESPACE}: học sinh THPT quan tâm CNTT"},
			{
				"title": f"{NAMESPACE}: học sinh THPT quan tâm CNTT",
				"is_public": 1,
				"filters": json.dumps(
					{
						"groups": [
							{"conditions": [{"field": "source", "operator": "=", "value": context["source"]}]}
						]
					}
				),
			},
		)

	# Marketing Engagement source=Migrated / Segment and the missing status
	# values are not reachable through the attribution commands (they only emit
	# Manual campaign_touch / event_participation), so cover them directly.
	_seed_marketing_engagement_variants(campaign_names[0], context)
	return {"campaigns": campaign_names, "renamed_campaigns": renamed_campaigns}


def _seed_marketing_engagement_variants(campaign: str, context: dict) -> None:
	if not frappe.db.table_exists("CRM Marketing Engagement"):
		return
	variants = [
		("event_participation", "No-show", "Migrated"),
		("event_participation", "Feedback Given", "Segment"),
		("campaign_touch", "Registered", "Migrated"),
	]
	pool_students = frappe.get_all(
		"CRM Lead",
		filters=_showcase_student_filters(),
		pluck="name",
		order_by="name",
		limit_page_length=0,
	)
	if not pool_students:
		return
	prev = frappe.flags.get("student_attribution_migration")
	frappe.flags.student_attribution_migration = True
	try:
		for _vi, (kind, status, source) in enumerate(variants):
			key = _idempotency_key("mkt-variant", kind, status, source)
			if frappe.db.exists("CRM Marketing Engagement", {"idempotency_key": key}):
				continue
			is_event = kind == "event_participation"
			ref_name = context["event"] if is_event else campaign
			# One evidence row per (kind, event/campaign, student). Walk the pool
			# until a Student without an existing row for this reference is found
			# so the doctype's per-reference dedup guard does not fire.
			student = None
			for cand in pool_students:
				clash = frappe.db.exists(
					"CRM Marketing Engagement",
					{"engagement_kind": kind, "reference_name": ref_name, "student": cand},
				)
				if not clash:
					student = cand
					break
			if not student:
				continue
			# No attribution command emits Migrated/Segment-sourced engagements or
			# the No-show / Feedback Given states; recorded directly under the
			# migration flag for queue-view coverage.
			frappe.get_doc(
				{
					"doctype": "CRM Marketing Engagement",
					"student": student,
					"engagement_kind": kind,
					"status": status,
					"source": source,
					"reference_doctype": "CRM Event" if is_event else "CRM Campaign",
					"reference_name": ref_name,
					"crm_campaign": ref_name if not is_event else None,
					"crm_event": ref_name if is_event else None,
					"touched_at": None if is_event else now_datetime(),
					"idempotency_key": key,
					"correlation_id": _idempotency_key("mkt-variant"),
					"notes": f"{NAMESPACE} marketing engagement variant",
				}
			).insert(ignore_permissions=True)
	finally:
		if prev is None:
			frappe.flags.pop("student_attribution_migration", None)
		else:
			frappe.flags.student_attribution_migration = prev


# ---------------------------------------------------------------------------
# Governance + reference coverage
# ---------------------------------------------------------------------------

_LEAD_SOURCE_CHANNELS = (
	("Showcase Social", "Social", "Approved"),
	("Showcase Search", "Search", "Proposed"),
	("Showcase Website", "Direct/Website", "Approved"),
	("Showcase Referral", "Referral", "Approved"),
	("Showcase Roadshow", "Event/Offline", "Retired"),
)


def _seed_governance(context: dict) -> dict:
	created: dict[str, Any] = {"lead_sources": [], "master_data_changes": []}

	for source_name, channel, approval_state in _LEAD_SOURCE_CHANNELS:
		name, _ = _upsert(
			"CRM Lead Source",
			{"source_name": source_name},
			{
				"source_name": source_name,
				"channel_family": channel,
				"details": f"{FPTU_ADMISSIONS_CONTEXT}; nguồn {channel.lower()} của {context['campus']}.",
			},
		)
		# approval_state is governed: set_governance_defaults() forces every plain
		# insert to "Approved". "Proposed"/"Retired" are only reached by driving
		# the proposal workflow, which the demo does not run, so pin them with a
		# guarded direct write (same rationale as _seed_edge_states).
		if approval_state != "Approved":
			frappe.db.set_value(
				"CRM Lead Source", name, "approval_state", approval_state, update_modified=False
			)
		created["lead_sources"].append(name)

	if frappe.db.table_exists("CRM Master Data Change"):
		prev = frappe.flags.get("crm_governance_log_insert")
		frappe.flags.crm_governance_log_insert = True
		try:
			specs = [
				("Create", "Proposed", f"{FPTU_HCMC_CAMPUS} — tuyển sinh 2026"),
				("Rename", "Applied", FPTU_HCMC_CAMPUS),
				("Retire", "Rejected", "Nguồn tuyển sinh FPTU HCMC 2019"),
				("Reactivate", "Applied", "Nguồn tuyển sinh FPTU HCMC trên Facebook 2022"),
				("Supersede", "Cancelled", "Nguồn hợp nhất tuyển sinh FPTU HCMC 2026"),
			]
			for action, status, new_value in specs:
				key = _idempotency_key("mdc", action.lower())
				existing = frappe.db.get_value("CRM Master Data Change", {"idempotency_key": key}, "name")
				if existing:
					doc = frappe.get_doc("CRM Master Data Change", existing)
					updates = {
						"reference_docname": context["campus"],
						"status": status,
						"reason": f"{NAMESPACE}: {FPTU_ADMISSIONS_CONTEXT}; {action} demo governance record",
						"new_value": new_value,
					}
					changed = any(doc.get(field) != value for field, value in updates.items())
					if changed:
						doc.update(updates)
						doc.save(ignore_permissions=True)
					created["master_data_changes"].append(doc.name)
					continue
				doc = frappe.get_doc(
					{
						"doctype": "CRM Master Data Change",
						"change_kind": "normal",
						"reference_doctype": "CRM Campus",
						"reference_docname": context["campus"],
						"action": action,
						"status": status,
						"registry_revision": "P9-DEC-001",
						"reason": f"{NAMESPACE}: {FPTU_ADMISSIONS_CONTEXT}; {action} demo governance record",
						"new_value": new_value,
						"idempotency_key": key,
						"correlation_id": _idempotency_key("mdc"),
						"proposed_by": "Administrator",
						"proposed_at": now_datetime(),
					}
				).insert(ignore_permissions=True)
				created["master_data_changes"].append(doc.name)
		finally:
			if prev is None:
				frappe.flags.pop("crm_governance_log_insert", None)
			else:
				frappe.flags.crm_governance_log_insert = prev
	return created


def _seed_reference_coverage(context: dict) -> dict:
	"""Reference/master-data state values not produced elsewhere."""
	created: dict[str, Any] = {}

	for name, program_type in _SHOWCASE_EDUCATION_PROGRAMS:
		created.setdefault("education_programs", []).append(
			_upsert(
				"CRM Education Program",
				{"program_name": name},
				{"program_name": name, "program_type": program_type},
			)[0]
		)

	# Score Template: seed_demo activates one; add one Draft and one Inactive so
	# the template status filter has every value the demo needs.
	for template_name, status in (
		("Showcase Draft Template", "Draft"),
		("Showcase Inactive Template", "Inactive"),
	):
		if not frappe.db.exists("CRM Score Template", {"template_name": template_name}):
			frappe.get_doc(
				{
					"doctype": "CRM Score Template",
					"template_name": template_name,
					"status": status,
					"fit_weight": 0.4,
					"intent_weight": 0.3,
					"engagement_weight": 0.3,
				}
			).insert(ignore_permissions=True)

	return created


def _seed_vocab_coverage(context: dict) -> None:
	"""Interaction outcome, Intent polarity/importance and Call Log vocabulary
	that the curated student journeys do not naturally hit. Runs after students
	so it can attach to a real demo Student."""
	rows = [
		("Resolved", "Positive", "High"),
		("Converted", "Positive", "Very High"),
		("Follow Up Needed", "Positive", "Medium"),
		("No Response", "Negative", "Medium"),
		("Data Error", "Negative", "Medium"),
		("Uncontactable", "Negative", "High"),
	]
	student = frappe.db.get_value("CRM Lead", _showcase_student_filters(), "name")
	if not student:
		return
	for idx, (outcome, polarity, importance) in enumerate(rows):
		# Key by the outcome value (not the loop index) so re-runs and row-order
		# edits keep each CRM Interaction pinned to the outcome it must cover.
		ext = _idempotency_key("vocab-interaction", outcome)
		interaction = frappe.db.get_value("CRM Interaction", {"external_id": ext}, "name")
		if interaction:
			frappe.db.set_value("CRM Interaction", interaction, "outcome", outcome, update_modified=False)
		if not interaction:
			interaction = (
				frappe.get_doc(
					{
						"doctype": "CRM Interaction",
						"student": student,
						"interaction_type": _ensure_interaction_type("Counseling"),
						"interaction_datetime": now_datetime() - timedelta(days=idx + 1),
						"external_id": ext,
						"direction": "inbound" if idx % 2 else "outbound",
						"outcome": outcome,
						"summary": f"{NAMESPACE} interaction outcome coverage: {outcome}",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		intent_type = seed_demo._ensure_intent_type(
			f"Showcase Intent {importance}", importance, f"Vocab coverage {importance}"
		)
		if not frappe.db.exists("CRM Intent", {"interaction": interaction, "intent_type": intent_type}):
			role = "Support" if idx % 2 else "Dominant"
			if role == "Dominant" and frappe.db.exists(
				"CRM Intent", {"interaction": interaction, "intent_role": "Dominant"}
			):
				# Only one Dominant intent is allowed per interaction; keep re-runs
				# and matrix edits from tripping that guard.
				role = "Support"
			frappe.get_doc(
				{
					"doctype": "CRM Intent",
					"interaction": interaction,
					"intent_type": intent_type,
					"confidence": 70,
					"intent_role": role,
					"polarity": polarity,
					"notes": f"{NAMESPACE} intent vocab coverage",
				}
			).insert(ignore_permissions=True)

	# outcome_code="completed" has no curated journey (the Enrolled scenario keeps
	# "qualified" so it stays compatible with its SLA qualifying evidence). Record
	# it directly on a dedicated interaction for the least-touched demo Student.
	comp_key = _idempotency_key("vocab-outcome-completed")
	if not frappe.db.exists("CRM Student Outcome", {"source_key": comp_key}):
		from crm.fcrm.student_engagement import record_outcome

		comp_student = (
			frappe.db.get_value(
				"CRM Lead", {**_showcase_student_filters(), "lifecycle_stage": "Lost"}, "name"
			)
			or student
		)
		comp_interaction = frappe.db.get_value("CRM Interaction", {"external_id": comp_key}, "name")
		if not comp_interaction:
			comp_interaction = (
				frappe.get_doc(
					{
						"doctype": "CRM Interaction",
						"student": comp_student,
						"interaction_type": _ensure_interaction_type("Counseling"),
						"interaction_datetime": now_datetime(),
						"external_id": comp_key,
						"direction": "outbound",
						"outcome": "Resolved",
						"summary": f"{NAMESPACE} outcome_code=completed coverage",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)
		try:
			record_outcome(
				student=comp_student,
				interaction=comp_interaction,
				outcome_code="completed",
				continuity_kind="terminal",
				continuity_reason="Đã hoàn tất toàn bộ hành trình tư vấn cho đợt tuyển sinh này.",
				qualification_evidence=[],
				source_key=comp_key,
				expected_revision=int(
					frappe.db.get_value("CRM Lead", comp_student, "engagement_revision") or 0
				),
				idempotency_key=comp_key,
				correlation_id=comp_key,
			)
		except Exception:
			frappe.db.rollback()

	# Call Log status/type coverage (Completed already produced by SLA call).
	for idx, (status, call_type) in enumerate(
		(("No Answer", "Outgoing"), ("Failed", "Outgoing"), ("Busy", "Incoming"), ("Completed", "Incoming"))
	):
		call_id = _idempotency_key("vocab-call", idx)
		if frappe.db.exists("Call Log", {"id": call_id}):
			continue
		frappe.get_doc(
			{
				"doctype": "Call Log",
				"id": call_id,
				"from": "0901900000",
				"to": "02873005588",
				"type": call_type,
				"status": status,
				"duration": 0 if status != "Completed" else 90,
				"start_time": now_datetime() - timedelta(hours=idx + 1),
			}
		).insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Edge states with no service path
# ---------------------------------------------------------------------------


def _seed_edge_states(context: dict, staff_context: dict) -> dict:
	"""One audited place for doctype states no whitelisted command can produce.

	Each write is ``frappe.db.set_value(..., update_modified=False)`` on a
	dedicated demo record, with the reason it has no service path inline.
	"""
	notes: list[str] = []
	pool = staff_context["pool"]

	# --- CRM Lead.intake_integrity_state: review_required / quarantined / legacy
	# submit_intake only ever leaves a *created* Student at 'resolved'; the review
	# and quarantine states live on Students created through conflict-resolution
	# paths that need a second conflicting identity we do not model in the curated
	# set. 'legacy' has no service path at all (migration-only provenance marker).
	for variant, state in (
		("review", "review_required"),
		("quarantine", "quarantined"),
		("legacy", "legacy"),
	):
		scenario = {
			"key": f"edge-{variant}",
			"student_name": _EDGE_DISPLAY_NAMES[variant],
			"gender": "Nam",
			"admission_method": "COMBINED",
			"email": _natural_email(_EDGE_DISPLAY_NAMES[variant]),
			"phone": f"090190030{['review', 'quarantine', 'legacy'].index(variant)}",
			"target_stage": "Lead",
		}
		try:
			doc = _ensure_student(scenario, context, pool)
			frappe.db.set_value(
				"CRM Lead", doc.name, "intake_integrity_state", state, update_modified=False
			)
			notes.append(f"CRM Lead {doc.name} intake_integrity_state={state} (no service path)")
		except Exception as exc:
			notes.append(f"edge intake_integrity_state={state} skipped: {exc}")

	# --- CRM Student Identity.identity_status = retracted
	# No whitelisted retraction command exists in crm/fcrm; retraction is an
	# operational data-fix. Retract the identity of the legacy edge Student.
	legacy_student = frappe.db.get_value(
		"CRM Lead",
		{"email": _natural_email(_EDGE_DISPLAY_NAMES["legacy"])},
		["name", "identity"],
		as_dict=True,
	)
	if legacy_student and legacy_student.get("identity"):
		frappe.db.set_value(
			"CRM Student Identity",
			legacy_student["identity"],
			"identity_status",
			"retracted",
			update_modified=False,
		)
		notes.append(
			f"CRM Student Identity {legacy_student['identity']} identity_status=retracted (no service path)"
		)

	# --- CRM Student SLA Attempt.status = closed / closed_inactive
	# The SLA state machine (crm_student_sla_attempt.py) allows these transitions
	# but no whitelisted command drives them; they are reconciled by an
	# inactivity job that is not part of the demo. Set on dedicated attempts so
	# the closed SLA queue views are populated.
	for variant, target in (("closed", "closed"), ("closed-inactive", "closed_inactive")):
		scenario = {
			"key": f"edge-sla-{variant}",
			"student_name": _EDGE_DISPLAY_NAMES[variant],
			"gender": "Nữ",
			"admission_method": "TRANSCRIPT_REVIEW",
			"email": _natural_email(_EDGE_DISPLAY_NAMES[variant]),
			"phone": f"09019004{['closed', 'closed-inactive'].index(variant):02d}",
			"target_stage": "Lead",
			"summary": "Hồ sơ có trạng thái SLA đã đóng",
			"notes": "Hồ sơ kiểm thử trạng thái SLA đã đóng.",
		}
		try:
			doc = _ensure_student(scenario, context, pool)
			_ensure_assigned(doc.name)
			attempt = _latest_sla_attempt(doc.name)
			if attempt:
				frappe.db.set_value(
					"CRM Student SLA Attempt", attempt.name, "status", target, update_modified=False
				)
				notes.append(f"CRM Student SLA Attempt {attempt.name} status={target} (no service path)")
		except Exception as exc:
			notes.append(f"edge SLA status={target} skipped: {exc}")

	# --- CRM Action states pending / requires-review (AI origin) / rejected / deferred
	# create_manual_action always emits an 'accepted' action; the pending /
	# rejected / deferred states belong to the recommendation-decision pipeline
	# which needs a CRM Recommendation the demo does not generate.
	base_student, base_owner = frappe.db.get_value(
		"CRM Lead",
		{**_showcase_student_filters(), "owner_staff": ["is", "set"]},
		["name", "owner_staff"],
	) or (None, None)
	if base_student:
		from crm.fcrm.student_decision import _command_key, create_manual_action

		for idx, (state, action_type, disposition) in enumerate(
			(
				("pending", "EMAIL", "MONITOR"),
				("requires-review", "MESSAGE", "MONITOR"),
				("rejected", "MEETING", "NURTURE"),
				("deferred", "EVENT_INVITE", "NURTURE"),
				("superseded", "CAMPUS_VISIT", "ACT"),
				("HANDOFF", "HANDOFF", "ACT"),
				("COUNSELING", "COUNSELING", "ACT"),
			)
		):
			idem = _idempotency_key("edge-action", idx)
			command_key = _command_key("manual_action", "Administrator", idem)
			existing = frappe.db.get_value("CRM Action", {"generation_idempotency_key": command_key}, "name")
			if existing:
				action_name = existing
			else:
				try:
					action_name = create_manual_action(
						base_student,
						action_type,
						f"{NAMESPACE} edge action {state}",
						idempotency_key=idem,
						due_at=now_datetime() + timedelta(days=1),
						priority="low",
						assignee_staff=base_owner,
					)["action"]
				except Exception as exc:
					notes.append(f"edge action {state} skipped: {exc}")
					continue
			target_state = (
				state
				if state
				in {
					"pending",
					"requires-review",
					"rejected",
					"deferred",
					"superseded",
				}
				else "accepted"
			)
			updates: dict[str, Any] = {"state": target_state, "disposition": disposition}
			if target_state in {"rejected", "superseded", "cancelled", "completed"}:
				# A terminal Action never keeps the student's single current slot.
				updates["current_slot"] = None
			frappe.db.set_value("CRM Action", action_name, updates, update_modified=False)
			notes.append(
				f"CRM Action {action_name} state={target_state} disposition={disposition} (no service path)"
			)

	# --- CRM Student Intake Review: review_type / review_status coverage
	_seed_intake_review_coverage(notes)

	frappe.db.commit()
	return {"edge_writes": notes}


def _seed_intake_review_coverage(notes: list[str]) -> None:
	"""Populate the intake-review board with every review_type and review_status.

	submit_intake with no admission year produces one real
	(missing_admission_cycle / open) review; the remaining review_type and
	review_status values have no reachable trigger in the curated data set, so
	they are written directly onto dedicated review rows.
	"""
	if not frappe.db.table_exists("CRM Student Intake Review"):
		return
	combos = [
		("identity_conflict", "attach_identity"),
		("duplicate_case", "applied"),
		("malformed_identifier", "reject"),
		("missing_admission_cycle", "open"),
		("ownership_topology", "approve_new_identity"),
		("legacy_contact_origin", "applied"),
	]
	for review_type, review_status in combos:
		key = _idempotency_key("intake-review", review_type)
		if frappe.db.exists("CRM Student Intake Review", {"review_key": key}):
			continue
		try:
			doc = frappe.get_doc(
				{
					"doctype": "CRM Student Intake Review",
					"review_key": key,
					"review_status": "open",
					"revision": 0,
					"review_type": review_type,
					"reason_sensitivity": "operational",
				}
			)
			doc.insert(ignore_permissions=True)
			if review_status != "open":
				frappe.db.set_value(
					"CRM Student Intake Review",
					doc.name,
					"review_status",
					review_status,
					update_modified=False,
				)
			notes.append(
				f"CRM Student Intake Review {doc.name} {review_type}/{review_status} (no service path)"
			)
		except Exception as exc:
			notes.append(f"intake review {review_type} skipped: {exc}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _seed_market_snapshots(context: dict) -> dict[str, int]:
	"""Create a dashboard-ready annual snapshot for a bounded school sample.

	Featured schools are always included so the market map and school detail have
	non-empty funnel metrics. Existing verified snapshots from another source are
	preserved; showcase-owned snapshots receive a new revision when CRM
	Student/Contact counts change after placement. Best effort -- a row the
	governance controller rejects is rolled back and skipped, never fatal.
	"""
	from crm.fcrm.doctype.crm_high_school_annual_snapshot.crm_high_school_annual_snapshot import (
		compute_crm_metrics,
		refresh_school_key_account,
	)

	year = context["admission_year"]
	if not frappe.db.exists("CRM Admission Year", year):
		return {"created": 0, "skipped": 0}
	schools = frappe.get_all(
		"CRM High School",
		fields=["name", "province", "school_code", "school_name"],
		order_by="province asc, school_code asc, name asc",
		limit_page_length=0,
	) or []
	featured = _priority_school_rows(schools)
	featured_names = {school["name"] for school in featured}
	remaining = [school for school in schools if school["name"] not in featured_names]
	rng = random.Random(SEED ^ 0x5000)
	rng.shuffle(remaining)
	# Keep the map fixture deliberately small. This makes the demo legible while
	# preserving a deterministic mix of key and non-key-account schools.
	targets = (featured + remaining)[:_MARKET_SNAPSHOT_SCHOOL_COUNT]
	target_school_names = [row["name"] for row in targets]
	# A previous full seed may have supplied a dashboard snapshot for every
	# canonical school. Remove only those showcase-owned rows and clear their
	# account flag, leaving imported/reference snapshots untouched.
	frappe.db.delete(
		"CRM High School Annual Snapshot",
		{
			"source_run": _DASHBOARD_SNAPSHOT_SOURCE_RUN,
			"high_school": ["not in", target_school_names],
		},
	)
	frappe.db.set_value(
		"CRM High School",
		{"name": ["not in", target_school_names]},
		"is_key_account",
		0,
		update_modified=False,
	)
	created = skipped = 0
	for index, row in enumerate(targets):
		school = row["name"]
		sp = _savepoint_name("showcase_market_snapshot", school)
		frappe.db.savepoint(sp)
		existing = frappe.get_all(
			"CRM High School Annual Snapshot",
			filters={"high_school": school, "admission_year": year, "period_type": "Annual"},
			fields=[
				"name", "admission_year", "measured_on", "period_type", "period", "revision",
				"timezone", "ne_target", "ne_actual", "ne_actual_semantics",
				"adjusted_ne_threshold", "applicant_count", "enrolled_count", "contact_count",
				"student_count", "conversion_count", "average_score", "conversion_rate",
				"enrollment_rate", "forecast_count", "context_raw_counts", "snapshot_date", "source_system", "source_run",
				"verification_status",
			],
			order_by="snapshot_date desc, recorded_at desc, revision desc, name desc",
			limit_page_length=0,
		) or []
		external_verified = next(
			(
				row
				for row in existing
				if row.get("verification_status") == "Verified"
				and row.get("source_run") not in _SHOWCASE_SNAPSHOT_SOURCE_RUNS
			),
			None,
		)
		showcase_snapshot = next(
			(row for row in existing if row.get("source_run") in _SHOWCASE_SNAPSHOT_SOURCE_RUNS),
			None,
		)
		r = _rng("market-snapshot", school)
		# Always consume the same random draws, whether this is the first run or
		# a rerun against an existing showcase snapshot.
		generated_threshold = r.randint(10, 20)
		generated_ne_actual = r.randint(18, 48)
		generated_forecast_factor = r.uniform(1.05, 1.35)
		generated_average_score = round(r.uniform(18.0, 28.5), 2)
		threshold, ne_actual = _market_snapshot_key_account_values(
			index, generated_threshold, generated_ne_actual
		)
		forecast = max(ne_actual, int(ne_actual * generated_forecast_factor))
		try:
			metrics = compute_crm_metrics(school, year)
		except Exception:
			skipped += 1
			continue
		derived = {
			field: metrics[field]
			for field in (
				"applicant_count", "enrolled_count", "contact_count", "student_count",
				"conversion_count", "conversion_rate", "enrollment_rate",
			)
		}
		average_score = (showcase_snapshot or {}).get("average_score") or generated_average_score
		detail_context = _director_school_detail_context(row, metrics)
		context_raw_counts = (showcase_snapshot or {}).get("context_raw_counts")
		if detail_context:
			context_raw_counts = {"director_school_detail": detail_context}
		if external_verified and not detail_context:
			skipped += 1
			continue
		if showcase_snapshot and all(
			showcase_snapshot.get(field) == value
			for field, value in {
				**derived,
				"adjusted_ne_threshold": threshold,
				"ne_actual": ne_actual,
				"forecast_count": forecast,
				"average_score": average_score,
			}.items()
		) and (
			not detail_context
			or _json_semantically_equal(showcase_snapshot.get("context_raw_counts"), context_raw_counts)
		):
			refresh_school_key_account(school)
			skipped += 1
			continue
		try:
			period = str((showcase_snapshot or (existing[0] if existing else {})).get("period") or year)
			period_rows = [row for row in existing if str(row.get("period") or year) == period]
			lineage_base = max(period_rows, key=lambda item: int(item.get("revision") or 0), default=None)
			revision = int(lineage_base.get("revision") or 0) + 1 if lineage_base else 1
			base = showcase_snapshot or lineage_base or {}
			frappe.get_doc(
				{
					"doctype": "CRM High School Annual Snapshot",
					"high_school": school,
					"admission_year": year,
					"measured_on": base.get("measured_on") or f"{year}-03-31",
					"snapshot_date": base.get("snapshot_date") or f"{year}-08-30",
					"period_type": base.get("period_type") or "Annual",
					"period": period,
					"revision": revision,
					"timezone": base.get("timezone") or "Asia/Ho_Chi_Minh",
					"ne_target": base.get("ne_target") or r.randint(32, 80),
					"ne_actual": ne_actual,
					"ne_actual_semantics": base.get("ne_actual_semantics") or "Official Achieved New Enter",
					"adjusted_ne_threshold": threshold,
					**derived,
					"average_score": average_score,
					"forecast_count": forecast,
					"context_raw_counts": context_raw_counts,
					"verification_status": "Verified",
					"is_locked": 1,
					"source_system": "demo-seed",
					"source_run": _DASHBOARD_SNAPSHOT_SOURCE_RUN,
					"supersedes": lineage_base.get("name") if lineage_base else None,
					"idempotency_fingerprint": _idempotency_key("market-snapshot", school, year, revision),
				}
			).insert(ignore_permissions=True)
			refresh_school_key_account(school)
			created += 1
		except Exception:
			try:
				frappe.db.rollback(save_point=sp)
			except Exception:
				frappe.db.rollback()
			skipped += 1
	frappe.db.commit()
	return {"created": created, "skipped": skipped}


def _seed_all() -> dict:
	frappe.set_user("Administrator")
	legacy_cleanup = _cleanup_legacy_seed_data()
	context = seed_demo._bootstrap()
	staff_context = seed_staff._bootstrap()
	if context["campus"] != FPTU_HCMC_CAMPUS or staff_context["campus"] != FPTU_HCMC_CAMPUS:
		raise frappe.ValidationError(
			f"Seed context must be scoped to {FPTU_HCMC_CAMPUS}; "
			f"got demo={context['campus']!r}, staff={staff_context['campus']!r}."
		)
	_ensure_lifecycle_statuses()
	_ensure_policies(staff_context["campus"], staff_context["pool"])
	reference = _seed_reference_coverage(context)
	# Create the governed source vocabulary before students reference it. Retired
	# or proposed sources remain in the governance matrix, but the bulk cohort
	# must only receive currently effective sources.
	governance = _seed_governance(context)
	# Commit the shared vocabulary / policy setup before the per-scenario loop:
	# a failing scenario there issues a bare rollback, which would otherwise
	# discard this setup and leave later steps unable to resolve lifecycle statuses.
	frappe.db.commit()

	school = _seed_school_domain(context, staff_context)
	school["dashboard_spotlight"] = _seed_dashboard_spotlight_relationships(staff_context)
	students, student_errors = _seed_students(context, staff_context)
	bulk_students, bulk_errors, bulk_metrics = _seed_bulk_students(context, staff_context)
	students.extend(bulk_students)
	student_errors.extend(bulk_errors)
	school_field_activity = seed_school_field_activity.seed(context)
	admission_funnel = seed_admission_funnel.seed(context)
	regional_performance = seed_director_regional_performance.seed(context)
	_seed_vocab_coverage(context)
	contacts = _seed_contacts(context, staff_context)
	market_snapshots = _seed_market_snapshots(context)
	marketing = _seed_marketing(context, staff_context)
	campaign_leads = _link_seed_leads_to_campaigns(students, marketing)
	campaign_intelligence = seed_director_campaign_intelligence.seed(context, marketing)
	revenue_forecast = seed_director_revenue_forecast.seed(context)
	edge = _seed_edge_states(context, staff_context)
	role_accounts = seed_role_accounts.execute()

	frappe.db.commit()
	return {
		"namespace": NAMESPACE,
		"legacy_cleanup": legacy_cleanup,
		"context": {
			"brand": "FPTU",
			"campus": FPTU_HCMC_CAMPUS,
			"focus": "admissions",
			"admission_year": "2026",
		},
		"accounts": {
			"password_site_config": seed_staff.FIXTURE_PASSWORD_SITE_CONFIG_KEY,
			"users": {
				**{email: meta["role"] for email, meta in seed_staff.CANONICAL_FIXTURE_USERS.items()},
				PROMOTER_EMAIL: "Promoter",
			},
		},
		"students": students,
		"student_errors": student_errors,
		"admission_funnel": admission_funnel,
		"regional_performance": regional_performance,
		"bulk": bulk_metrics,
		"contacts": contacts,
		"school_domain": school,
		"school_field_activity": school_field_activity,
		"market_snapshots": market_snapshots,
		"marketing": marketing,
		"campaign_leads": campaign_leads,
		"campaign_intelligence": campaign_intelligence,
		"revenue_forecast": revenue_forecast,
		"governance": governance,
		"reference": reference,
		"edge_states": edge,
		"role_accounts": role_accounts,
		"known_gaps": list(KNOWN_GAPS),
	}


def execute(strict: bool = True) -> dict:
	"""Seed the full CRM demo dataset on ``crm.localhost`` only.

	With ``strict`` (the default) student or bulk-richness errors raise after the
	manifest is printed, so ``task seed`` fails loudly instead of exiting 0 on a
	partial seed. Pass ``strict=False`` to inspect a partial run.
	"""
	_assert_local_site()
	ensure_local_integrity_keys()
	_assert_integrity_keys()
	with _temporary_local_flags():
		result = _seed_all()
	print(frappe.as_json(result))
	bulk_errors = int((result.get("bulk") or {}).get("errors", 0))
	funnel_errors = len((result.get("admission_funnel") or {}).get("errors", []))
	if strict and (result.get("student_errors") or bulk_errors or funnel_errors):
		raise frappe.ValidationError(
			f"Seed completed with {len(result.get('student_errors') or [])} scenario error(s) "
			f"{bulk_errors} bulk-richness error(s), and {funnel_errors} funnel error(s); "
			"see the manifest above."
		)
	return result


# ---------------------------------------------------------------------------
# verify() / reset()
# ---------------------------------------------------------------------------


def _distinct_values(doctype: str, field: str, filters: dict | None = None) -> set[str]:
	if not frappe.db.table_exists(doctype):
		return set()
	try:
		rows = frappe.get_all(
			doctype, filters=filters or {}, fields=[field], distinct=True, limit_page_length=0
		)
	except Exception:
		return set()
	return {str(row.get(field)) for row in rows if row.get(field) not in (None, "")}


def _has_active_policy_for_showcase_scope(doctype: str, filters: dict | None) -> bool:
	"""Accept a pre-existing active policy when publication overlap forbids a clone."""
	if doctype not in {"CRM Student Routing Policy", "CRM Student SLA Policy"}:
		return False
	rows = frappe.get_all(
		doctype,
		filters=filters or {},
		fields=["campus", "student_pool"],
		limit_page_length=0,
	) or []
	return any(
		frappe.db.exists(
			doctype,
			{"campus": row.get("campus"), "student_pool": row.get("student_pool"), "status": "active"},
		)
		for row in rows
		if row.get("campus") and row.get("student_pool")
	)


def _coverage_scope() -> dict[str, dict]:
	"""Row filter per COVERAGE_MATRIX doctype so verify() checks only what this
	seed creates -- a blanket table scan would let unrelated manual QA rows
	satisfy the matrix.

	execute() runs the seed_demo + seed_staff bootstrap, so the one fixture this
	seed deliberately reuses -- the single Active score template, which the
	doctype only allows one of -- is included by name.
	"""
	ns = f"%{NAMESPACE}%"
	none = ["__seed_showcase_no_match__"]

	def pluck(doctype, filters, field="name"):
		return frappe.get_all(doctype, filters=filters, pluck=field, limit_page_length=0) or list(none)

	students = pluck("CRM Lead", _showcase_student_filters())
	contacts = pluck("CRM Student", {"email": ["in", [_contact_email(row) for row in _ALL_CONTACT_ROWS]]})
	identities = [
		i
		for i in frappe.get_all(
			"CRM Lead", filters={"name": ["in", students]}, pluck="identity", limit_page_length=0
		)
		if i
	] or list(none)
	interactions = list(
		set(pluck("CRM Interaction", {"student": ["in", students]}))
		| set(pluck("CRM Interaction", {"external_id": ["like", ns]}))
	)
	# The school domain is real imported data now; the rows this seed uses are the
	# curated key-account schools, resolved through their annual snapshots.
	school_children = set(pluck("CRM School Activity", {}, "high_school")) | set(
		pluck("CRM School Stakeholder", {}, "high_school")
	)
	schools = sorted(s for s in school_children if s and s != none[0]) or list(none)
	by_student = {"student": ["in", students]}
	return {
		"CRM Lead": {"name": ["in", students]},
		"CRM Student SLA Attempt": dict(by_student),
		"CRM Student Identity": {"name": ["in", identities]},
		"CRM Student Intake Review": {"review_key": ["like", ns]},
		"CRM Student Outcome": dict(by_student),
		"CRM Action": dict(by_student),
		"CRM Interaction": {"name": ["in", interactions]},
		"CRM Intent": {"interaction": ["in", interactions]},
		"CRM Student": {"name": ["in", contacts]},
		"CRM Contact Consent Event": {"contact": ["in", contacts]},
		"CRM High School": {"name": ["in", schools]},
		"CRM High School Annual Snapshot": {"high_school": ["in", schools]},
		"CRM School Activity": {"owner_staff": ["is", "set"]},
		"CRM School Stakeholder": {"owner_staff": ["is", "set"]},
		"CRM Campaign": {"title": ["in", _SHOWCASE_CAMPAIGN_TITLES]},
		"CRM Marketing Engagement": {"correlation_id": ["like", ns]},
		"CRM Master Data Change": {"correlation_id": ["like", ns]},
		"CRM Lead Source": {"source_name": ["like", "Showcase %"]},
		"CRM Score Template": {
			"template_name": ["in", [*_SHOWCASE_SCORE_TEMPLATES, seed_demo.TEMPLATE_NAME]]
		},
		"CRM Student Routing Policy": {"policy_key": ["like", ns]},
		"CRM Student SLA Policy": {"policy_key": ["like", ns]},
		"CRM Education Program": {"program_name": ["in", _SHOWCASE_PROGRAM_NAMES]},
	}


def _verify_bulk_invariants() -> dict[str, Any]:
	"""Verify count, school coverage, location derivation and regional spread.

	The ten-student cap applies to the generated bulk cohort. Curated workflow and
	edge-state students intentionally share a few spotlight schools for demos, so
	their combined showcase count is reported but is not subject to the bulk cap.
	"""
	schools = _canonical_school_rows()
	school_by_name = {row["name"]: row for row in schools}
	all_school_count = frappe.db.count("CRM High School")
	bulk_rows = frappe.get_all(
		"CRM Lead",
		filters={"import_source_id": ["like", f"{seed_bulk_realistic.BULK_IMPORT_NAMESPACE}:%"]},
		fields=["name", "email", "high_school", "province", "ward"],
		limit_page_length=0,
	) or []
	by_school: dict[str, int] = {}
	location_mismatches: list[str] = []
	for row in bulk_rows:
		school_name = row.get("high_school")
		by_school[school_name] = by_school.get(school_name, 0) + 1
		school = school_by_name.get(school_name)
		if not school or row.get("province") != school.get("province") or row.get("ward") != school.get("ward"):
			location_mismatches.append(row["name"])
	missing_schools = sorted(set(school_by_name) - set(by_school))
	max_students_per_school = max(by_school.values(), default=0)
	region_totals: dict[float, int] = {}
	region_school_counts: dict[float, int] = {}
	for school_name, school in school_by_name.items():
		weight = seed_bulk_realistic.province_weight(school.get("province"))
		region_totals[weight] = region_totals.get(weight, 0) + by_school.get(school_name, 0)
		region_school_counts[weight] = region_school_counts.get(weight, 0) + 1
	region_averages = {
		str(weight): round(region_totals[weight] / region_school_counts[weight], 3)
		for weight in sorted(region_school_counts, reverse=True)
		if region_school_counts[weight]
	}
	baseline = region_averages.get("1.0", 0)
	regional_bias_ok = (
		bool(region_averages.get("2.0"))
		and bool(region_averages.get("1.5"))
		and region_averages["2.0"] > baseline
		and region_averages["1.5"] > baseline
	)
	showcase_emails = set(_showcase_student_emails())
	showcase_rows = frappe.get_all(
		"CRM Lead",
		filters={"email": ["in", list(showcase_emails)]},
		fields=["name", "email", "high_school"],
		limit_page_length=0,
	) or []
	seen_emails = {row.get("email") for row in showcase_rows}
	showcase_by_school: dict[str | None, int] = {}
	for row in showcase_rows:
		school_name = row.get("high_school")
		showcase_by_school[school_name] = showcase_by_school.get(school_name, 0) + 1
	max_showcase_students_per_school = max(showcase_by_school.values(), default=0)
	result = {
		"expected_showcase_students": TARGET_SHOWCASE_STUDENTS,
		"showcase_student_count": len(showcase_rows),
		"missing_showcase_emails": sorted(showcase_emails - seen_emails),
		"duplicate_showcase_emails": len(showcase_rows) - len(seen_emails),
		"expected_bulk_students": len(BULK_SCENARIOS),
		"bulk_student_count": len(bulk_rows),
		"school_count": len(schools),
		"all_school_count": all_school_count,
		"schools_without_bulk_student": missing_schools,
		"location_mismatch_count": len(location_mismatches),
		"max_bulk_students_per_school": max_students_per_school,
		"max_showcase_students_per_school": max_showcase_students_per_school,
		"region_average_students_per_school": region_averages,
		"regional_bias_ok": regional_bias_ok,
	}
	result["ok"] = (
		result["showcase_student_count"] == TARGET_SHOWCASE_STUDENTS
		and not result["missing_showcase_emails"]
		and not result["duplicate_showcase_emails"]
		and result["bulk_student_count"] == len(BULK_SCENARIOS)
		and not missing_schools
		and not location_mismatches
		and max_students_per_school <= seed_bulk_realistic.DEFAULT_PER_SCHOOL_CAP
		and regional_bias_ok
	)
	return result


def verify(strict: bool = True) -> dict:
	"""Assert every COVERAGE_MATRIX value has >=1 record this seed created.

	Row scope per doctype comes from ``_coverage_scope()``. With ``strict`` (the
	default) an uncovered field raises after the report is printed so
	``task seed-verify`` fails loudly. ``KNOWN_GAPS`` are documented separately
	and never counted as a failure.
	"""
	_assert_local_site()
	scope = _coverage_scope()
	covered: dict[str, list[str]] = {}
	missing: dict[str, list[str]] = {}
	for doctype, fields in COVERAGE_MATRIX.items():
		for field, expected in fields.items():
			filters = scope.get(doctype)
			present = _distinct_values(doctype, field, filters)
			if (
				field == "status"
				and "active" in expected
				and "active" not in present
				and _has_active_policy_for_showcase_scope(doctype, filters)
			):
				# Policy publication correctly rejects overlapping active clones. The
				# baseline active policy still covers the same campus/pool operation.
				present.add("active")
			key = f"{doctype}.{field}"
			hit = [value for value in expected if value in present]
			gap = [value for value in expected if value not in present]
			covered[key] = hit
			if gap:
				missing[key] = gap
	result = {
		"namespace": NAMESPACE,
		"covered_fields": len(covered),
		"fields_with_gaps": missing,
		"known_gaps": list(KNOWN_GAPS),
		"bulk_invariants": _verify_bulk_invariants(),
	}
	result["ok"] = not missing and result["bulk_invariants"]["ok"]
	print(frappe.as_json(result))
	if strict and (missing or not result["bulk_invariants"]["ok"]):
		raise frappe.ValidationError(
			f"Demo verification failed: coverage_gaps={len(missing)}, "
			f"bulk_invariants_ok={result['bulk_invariants']['ok']}"
		)
	return result


# Business rows this seed owns: (doctype, field, LIKE pattern). Append-only audit
# / receipt / ledger rows are intentionally left in place. CRM Campaign, CRM
# Education Program and the workbook-imported school domain (CRM Province / Ward /
# High School and the TS annual snapshots) are treated as reference data and kept;
# a full re-demo goes through `bench reinstall` (see reset() docstring).
_RESET_DOCTYPES = (
	("CRM Marketing Engagement", "correlation_id", f"%{NAMESPACE}%"),
	# Geography opportunity fixtures are no longer part of the Director market
	# contract, but remove rows created by older showcase runs during reset.
	("CRM Geography Market Snapshot", "source", "demo-seed"),
	("CRM Master Data Change", "correlation_id", f"%{NAMESPACE}%"),
	("CRM Student Intake Review", "review_key", f"%{NAMESPACE}%"),
	# CRM Contact Consent Event is append-only (on_trash blocks deletion); its
	# rows are left behind with their now-deleted Contact link, like the other
	# audit rows noted below.
	("CRM Score Template", "template_name", "Showcase %"),
	("CRM Lead Source", "source_name", "Showcase %"),
	("CRM Segment", "title", f"%{NAMESPACE}%"),
	("CRM Campaign Spend", "notes", f"%{NAMESPACE}%"),
	("CRM Student Routing Policy", "policy_key", f"%{NAMESPACE}%"),
	("CRM Student SLA Policy", "policy_key", f"%{NAMESPACE}%"),
	("CRM Admission Offering", "offering_key", f"{seed_admission_funnel.NAMESPACE}|%"),
)

# Append-only audit rows purged with a raw delete during reset() (crm.localhost
# only) because their on_trash guard blocks delete_doc and a surviving row makes
# the next execute() replay a command against a deleted Student.
_RAW_PURGE_DOCTYPES = (
	("CRM Student Outcome", "source_key"),
	("CRM Contact Consent Event", "note"),
)

_LEGACY_DEMO_USERS = (
	"sarah.demo@example.com",
	"john.demo@example.com",
	"emily.demo@example.com",
	"nguyen-minh-khoi.sale@example.test",
	"le-thanh-huong.leadsales@example.test",
	"pham-bao-chau.marketing@example.test",
	"tran-quoc-duy.director@example.test",
	"sale@gmail.com",
	"sale@example.com",
	"leadsales@gmail.com",
	"leadsales@example.com",
	"marketing@gmail.com",
	"marketing@example.com",
	"director@gmail.com",
	"director@example.com",
	"vo-thi-lan.promoter@example.test",
	"nguyen-minh-anh-admissions-demo@example.test",
	"tran-quoc-minh-admissions-demo@example.test",
	"phase6.sales@example.test",
	"e2e.local-service@example.test",
	"e2e.other-campus@example.test",
	"e2e.sales@example.test",
	"e2e.marketing@example.test",
	"e2e.lead-sales@example.test",
	"e2e.admissions-director@example.test",
	"e2e.admin@example.test",
)

_LEGACY_STUDENT_FILTERS = (
	{"email": ["like", "e2e-fpt-2026-%@example.test"]},
	{"email": ["like", "pw-%@example.test"]},
	{"email": "phase6.local.student@example.test"},
	{"email": "nguyen-minh-anh-admissions-demo@example.test"},
)


def _cleanup_legacy_seed_data() -> dict[str, int]:
	"""Remove records owned by seed paths superseded by this canonical seed.

	This is deliberately allow-listed and local-only. Imported school/reference
	data and rows created by :mod:`seed_showcase` are never matched here.
	"""
	deleted: dict[str, int] = {}

	def delete_docs(doctype: str, names: list[str], *, raw: bool = False) -> None:
		if not names or not frappe.db.table_exists(doctype):
			return
		count = 0
		for name in sorted(set(names)):
			if not frappe.db.exists(doctype, name):
				continue
			if raw:
				frappe.db.delete(doctype, {"name": name})
			else:
				try:
					frappe.delete_doc(
						doctype, name, force=True, ignore_permissions=True, delete_permanently=True
					)
				except Exception:
					continue
			count += 1
		if count:
			deleted[doctype] = deleted.get(doctype, 0) + count

	# The old FCRM Settings seed stored exact names in site defaults. Clear those
	# first, including records created by the standard three-row demo cohort.
	legacy_defaults = (
		("CRM Score History", "crm_demo_score_histories"),
		("Call Log", "crm_demo_call_logs"),
		("Task", "crm_demo_tasks"),
		("FCRM Note", "crm_demo_notes"),
		("CRM Interaction", "crm_demo_interactions"),
		("CRM Student", "crm_demo_crm_contacts"),
		("CRM Lead", "crm_demo_students"),
		("CRM Score Template", "crm_demo_score_templates"),
	)
	for doctype, key in legacy_defaults:
		try:
			names = json.loads(frappe.db.get_default(key) or "[]")
		except (TypeError, ValueError):
			names = []
		delete_docs(doctype, names)
		frappe.db.set_default(key, None)
	frappe.db.set_default("crm_demo_data_created", None)

	legacy_students: set[str] = set()
	for filters in _LEGACY_STUDENT_FILTERS:
		legacy_students.update(
			frappe.get_all("CRM Lead", filters=filters, pluck="name", limit_page_length=0)
		)
	legacy_student_list = sorted(legacy_students)
	if frappe.db.table_exists("CRM Student Identity Identifier"):
		from crm.fcrm.student_intake import _find_observation_roots

		for scenario in SCENARIOS:
			for identifier_type, value in (("phone", scenario["phone"]), ("email", scenario["email"])):
				for root in _find_observation_roots(identifier_type, value):
					wrong_students = frappe.get_all(
						"CRM Lead",
						filters={"identity": root["identity"]},
						fields=["name", "email"],
					)
					if any(row.email == scenario["email"] for row in wrong_students):
						continue
					wrong_observations = frappe.get_all(
						"CRM Student Identity Identifier",
						filters={
							"parent": root["identity"],
							"identifier_type": identifier_type,
							"keyed_digest": root["digest"],
						},
						pluck="name",
					)
					delete_docs("CRM Student Identity Identifier", wrong_observations, raw=True)
	legacy_interactions = (
		frappe.get_all("CRM Interaction", filters={"student": ["in", legacy_student_list]}, pluck="name")
		if legacy_student_list and frappe.db.table_exists("CRM Interaction")
		else []
	)
	legacy_conversions = (
		frappe.get_all(
			"CRM Student Contact Conversion",
			filters={"student": ["in", legacy_student_list]},
			fields=["name", "contact"],
		)
		if legacy_student_list and frappe.db.table_exists("CRM Student Contact Conversion")
		else []
	)
	legacy_contacts = [row.contact for row in legacy_conversions if row.contact]
	legacy_recommendations = (
		frappe.get_all(
			"CRM Recommendation",
			filters={"target_type": "CRM Lead", "target_id": ["in", legacy_student_list]},
			pluck="name",
		)
		if legacy_student_list and frappe.db.table_exists("CRM Recommendation")
		else []
	)
	legacy_actions = (
		frappe.get_all("CRM Action", filters={"student": ["in", legacy_student_list]}, pluck="name")
		if legacy_student_list and frappe.db.table_exists("CRM Action")
		else []
	)
	legacy_identity_names = (
		frappe.get_all("CRM Lead", filters={"name": ["in", legacy_student_list]}, pluck="identity")
		if legacy_student_list
		else []
	)
	legacy_case_names = (
		frappe.get_all(
			"CRM Student Case Key",
			filters={"canonical_student": ["in", legacy_student_list]},
			pluck="name",
		)
		if legacy_student_list and frappe.db.table_exists("CRM Student Case Key")
		else []
	)
	if frappe.db.table_exists("CRM Student Command Receipt"):
		stale_receipts = [
			row.name
			for row in frappe.get_all(
				"CRM Student Command Receipt",
				filters={"command_key": ["like", f"{NAMESPACE}%"]},
				fields=["name", "target_student"],
			)
			if not row.target_student or not frappe.db.exists("CRM Lead", row.target_student)
		]
		delete_docs("CRM Student Command Receipt", stale_receipts, raw=True)
		orphan_receipts = [
			row.name
			for row in frappe.get_all(
				"CRM Student Command Receipt",
				filters={"target_student": ["is", "set"]},
				fields=["name", "target_student"],
			)
			if row.target_student and not frappe.db.exists("CRM Lead", row.target_student)
		]
		delete_docs("CRM Student Command Receipt", orphan_receipts, raw=True)
		expected_receipt_emails = {
			f"{NAMESPACE}:{scenario['key']}": scenario["email"] for scenario in SCENARIOS
		}
		stale_identity_receipts = [
			row.name
			for row in frappe.get_all(
				"CRM Student Command Receipt",
				filters={"correlation_token": ["like", f"{NAMESPACE}:%"]},
				fields=["name", "target_student", "correlation_token"],
			)
			if row.correlation_token in expected_receipt_emails
			and row.target_student
			and frappe.db.get_value("CRM Lead", row.target_student, "email")
			!= expected_receipt_emails[row.correlation_token]
		]
		delete_docs("CRM Student Command Receipt", stale_identity_receipts, raw=True)
	if frappe.db.table_exists("CRM Student Case Key"):
		orphan_cases = [
			row.name
			for row in frappe.get_all(
				"CRM Student Case Key",
				fields=["name", "canonical_student", "source_student"],
			)
			if (not row.canonical_student and not row.source_student)
			or (
				row.canonical_student
				and not frappe.db.exists("CRM Lead", row.canonical_student)
				and row.source_student
				and not frappe.db.exists("CRM Lead", row.source_student)
			)
		]
		delete_docs("CRM Student Case Key", orphan_cases, raw=True)

	# Remove append-only rows with a raw delete. They otherwise block deletion of
	# the student or make a future seed replay an old command against a new row.
	for doctype, field in (
		("CRM Student Command Receipt", "target_student"),
		("CRM Student Lifecycle Event", "student"),
		("CRM Student Ownership Event", "student"),
		("CRM Student Outcome", "student"),
		("CRM Contact Consent Event", "student"),
	):
		if legacy_student_list and frappe.db.table_exists(doctype):
			rows = frappe.get_all(doctype, filters={field: ["in", legacy_student_list]}, pluck="name")
			delete_docs(doctype, rows, raw=True)
	if legacy_recommendations or legacy_actions:
		delete_docs(
			"CRM Agent Event",
			frappe.get_all(
				"CRM Agent Event",
				filters={"aggregate_name": ["in", [*legacy_recommendations, *legacy_actions]]},
				pluck="name",
			)
			if frappe.db.table_exists("CRM Agent Event")
			else [],
			raw=True,
		)

	# Remove all normal child records before their legacy Student parent.
	for doctype, field in (
		("CRM Student SLA Attempt", "student"),
		("CRM Student Routing Request", "student"),
		("CRM Action", "student"),
		("CRM Score History", "student"),
		("Task", "student"),
		("CRM Student Contact Conversion", "student"),
		("File", "attached_to_name"),
	):
		if not legacy_student_list or not frappe.db.table_exists(doctype):
			continue
		delete_docs(
			doctype, frappe.get_all(doctype, filters={field: ["in", legacy_student_list]}, pluck="name")
		)
	if legacy_student_list and frappe.db.table_exists("CRM Recommendation"):
		delete_docs(
			"CRM Recommendation",
			frappe.get_all(
				"CRM Recommendation",
				filters={"target_type": "CRM Lead", "target_id": ["in", legacy_student_list]},
				pluck="name",
			),
		)
	if legacy_student_list and frappe.db.table_exists("File"):
		delete_docs(
			"File",
			frappe.get_all(
				"File",
				filters={
					"attached_to_doctype": "CRM Lead",
					"attached_to_name": ["in", legacy_student_list],
				},
				pluck="name",
			),
		)
	if legacy_actions:
		delete_docs("CRM Action", legacy_actions)
	if legacy_recommendations:
		delete_docs("CRM Recommendation", legacy_recommendations)
	if legacy_interactions and frappe.db.table_exists("CRM Intent"):
		delete_docs(
			"CRM Intent",
			frappe.get_all("CRM Intent", filters={"interaction": ["in", legacy_interactions]}, pluck="name"),
		)
	delete_docs("CRM Interaction", legacy_interactions)

	# Conversion can point to a CRM Student; remove only contacts reached from
	# the legacy conversion rows.
	delete_docs("CRM Student", [name for name in legacy_contacts if name])
	if frappe.db.table_exists("CRM Student"):
		delete_docs(
			"CRM Student",
			frappe.get_all(
				"CRM Student",
				filters={"email": ["like", "%showcase@example.test"]},
				pluck="name",
			),
		)
	if frappe.db.table_exists("CRM Person"):
		legacy_persons = frappe.get_all(
			"CRM Person", filters={"full_name": ["like", "Thầy/Cô phụ trách%"]}, pluck="name"
		)
		if legacy_persons and frappe.db.table_exists("CRM School Stakeholder"):
			delete_docs(
				"CRM School Stakeholder",
				frappe.get_all(
					"CRM School Stakeholder", filters={"person": ["in", legacy_persons]}, pluck="name"
				),
			)
		delete_docs("CRM Person", legacy_persons)
	delete_docs("CRM Lead", legacy_student_list)
	delete_docs("CRM Student Case Key", legacy_case_names)
	delete_docs("CRM Student Identity", [name for name in legacy_identity_names if name])

	# Dedicated accounts and their staff/contact records are not part of the
	# canonical account list. Never match ordinary users by role or name.
	if frappe.db.table_exists("CRM Staff"):
		staff_names = frappe.get_all(
			"CRM Staff", filters={"user": ["in", list(_LEGACY_DEMO_USERS)]}, pluck="name"
		)
		delete_docs("CRM Staff", staff_names)
	for email in _LEGACY_DEMO_USERS:
		if not frappe.db.exists("User", email):
			continue
		contacts = (
			frappe.get_all("Contact", filters={"user": email}, pluck="name")
			if frappe.db.table_exists("Contact")
			else []
		)
		if contacts:
			for child in ("Contact Email", "Contact Phone", "Dynamic Link"):
				if frappe.db.table_exists(child):
					frappe.db.delete(child, {"parent": ["in", contacts]})
			frappe.db.delete("Contact", {"name": ["in", contacts]})
		if frappe.db.table_exists("Notification"):
			frappe.db.delete("Notification", {"from_user": email})
			frappe.db.delete("Notification", {"to_user": email})
		if frappe.db.table_exists("Notification Settings"):
			frappe.db.delete("Notification Settings", {"name": email})
		delete_docs("User", [email])

	# E2E and local fixtures also created isolated topology and OAuth records.
	for doctype, filters in (
		("OAuth Bearer Token", {"user": ["in", list(_LEGACY_DEMO_USERS)]}),
		("OAuth Client", {"app_name": ["like", "E2E-FPT-2026%"]}),
		("CRM Team", {"team_name": ["like", "PW-LEAD-%"]}),
		("CRM Team", {"team_name": ["like", "E2E-FPT-2026%"]}),
		("CRM Team", {"team_name": "Phase 6 Local Sales Team"}),
		("CRM Student Pool", {"pool_name": ["like", "PW-LEAD-%"]}),
		("CRM Student Pool", {"pool_name": ["like", "E2E-FPT-2026%"]}),
		("CRM Department", {"department_name": ["like", "E2E-FPT-2026%"]}),
		("CRM Department", {"department_name": ["like", "PW-LEAD-%"]}),
		("CRM Department", {"department_name": "Phòng Tư vấn tuyển sinh Demo"}),
		("CRM Department", {"department_name": "Phase 6 Local Admissions"}),
		("CRM Campus", {"campus_name": ["like", "E2E-FPT-2026%"]}),
		("CRM Campus", {"campus_name": ["like", "PW-LEAD-%"]}),
		("CRM Campus", {"campus_name": "Phase 6 Local Campus"}),
	):
		if frappe.db.table_exists(doctype):
			delete_docs(doctype, frappe.get_all(doctype, filters=filters, pluck="name"))

	frappe.db.commit()
	return deleted


def reset() -> dict:
	"""Delete this seed's business rows on crm.localhost. Audit / receipt rows are kept.

	This is a best-effort teardown, not a full cycle: Frappe append-only rows
	(command receipts, SLA / lifecycle / ownership events, score history) survive,
	and reused CRM Student names can inherit a stale SLA attempt. The supported
	way to get a pristine dataset is ``bench reinstall`` + ``install-app crm`` +
	``bench migrate`` + ``execute()``.
	"""
	_assert_local_site()
	frappe.set_user("Administrator")
	deleted: dict[str, int] = {}
	kept_note = (
		"Append-only rows (receipts, SLA events, lifecycle events, outcomes, "
		"score history, ownership events) are intentionally left in place."
	)

	with _temporary_local_flags():
		legacy_cleanup = _cleanup_legacy_seed_data()
		# CRM Lead + everything keyed to it.
		students = frappe.get_all(
			"CRM Lead", filters=_showcase_student_filters(), pluck="name", limit_page_length=0
		)
		legacy_students = frappe.get_all(
			"CRM Lead",
			filters={"email": ["like", _LEGACY_STUDENT_EMAIL_LIKE]},
			pluck="name",
			limit_page_length=0,
		)
		students = sorted(set(students) | set(legacy_students))
		for student in students:
			for dt in ("CRM Admission Application", "CRM Action", "CRM Interaction", "Task"):
				for name in frappe.get_all(
					dt, filters={"student": student}, pluck="name", limit_page_length=0
				):
					frappe.delete_doc(dt, name, force=True, ignore_permissions=True, delete_permanently=True)
			frappe.delete_doc(
				"CRM Lead", student, force=True, ignore_permissions=True, delete_permanently=True
			)
		deleted["CRM Lead"] = len(students)

		contacts = frappe.get_all(
			"CRM Student",
			filters={"email": ["in", [_contact_email(row) for row in _ALL_CONTACT_ROWS]]},
			pluck="name",
			limit_page_length=0,
		)
		legacy_contacts = frappe.get_all(
			"CRM Student",
			filters={"email": ["like", f"%{NAMESPACE}@example.test"]},
			pluck="name",
			limit_page_length=0,
		)
		contacts = sorted(set(contacts) | set(legacy_contacts))
		for name in contacts:
			frappe.delete_doc(
				"CRM Student", name, force=True, ignore_permissions=True, delete_permanently=True
			)
		deleted["CRM Student"] = len(contacts)

		for doctype, field, pattern in _RESET_DOCTYPES:
			if not frappe.db.table_exists(doctype):
				continue
			names = frappe.get_all(
				doctype, filters={field: ["like", pattern]}, pluck="name", limit_page_length=0
			)
			for name in names:
				try:
					frappe.delete_doc(
						doctype, name, force=True, ignore_permissions=True, delete_permanently=True
					)
				except Exception:
					pass
			deleted[doctype] = len(names)

		# crm.localhost-only: append-only audit rows (command receipts, outcomes)
		# refuse delete_doc via on_trash. Left in place they make the next
		# execute() replay intake / outcome commands against now-deleted Students
		# ("replay target is no longer available"). Clear this namespace's rows
		# with a raw delete so reset() + execute() is a clean, repeatable cycle.
		for doctype, field in _RAW_PURGE_DOCTYPES:
			if not frappe.db.table_exists(doctype):
				continue
			before = frappe.db.count(doctype, {field: ["like", f"%{NAMESPACE}%"]})
			frappe.db.delete(doctype, {field: ["like", f"%{NAMESPACE}%"]})
			deleted[doctype] = before

		# Command receipts key on hashed digests, not the namespace, so match them
		# by the plaintext correlation token we pass. Rows for a now-deleted
		# Student are only purged when they also carry this namespace's token, so
		# receipts from unrelated manual QA are never touched.
		if frappe.db.table_exists("CRM Student Command Receipt"):
			receipt_filter = {"correlation_token": ["like", f"%{NAMESPACE}%"]}
			deleted["CRM Student Command Receipt"] = frappe.db.count(
				"CRM Student Command Receipt", receipt_filter
			)
			frappe.db.delete("CRM Student Command Receipt", receipt_filter)
		frappe.db.commit()

	result = {
		"namespace": NAMESPACE,
		"deleted": deleted,
		"legacy_cleanup": legacy_cleanup,
		"note": kept_note,
	}
	print(frappe.as_json(result))
	return result
