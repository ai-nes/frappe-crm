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
import secrets
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import frappe
from frappe.utils import now_datetime

from crm.demo import seed_demo, seed_staff

LOCAL_SITE = "crm.localhost"
NAMESPACE = "crm-demo-showcase"
# Every curated scenario Student carries a synthetic e-mail ending with this
# marker; CRM Student has no free-text namespace field, so the e-mail is the
# stable handle for coverage backfill and for reset().
# Curated scenario Students use "<name>.showcase@example.test"; edge-state
# Students use "edge-<x>.crm-demo-showcase@example.test". This LIKE matches both.
_STUDENT_EMAIL_SUFFIX = "showcase@example.test"
_STUDENT_EMAIL_LIKE = "%" + _STUDENT_EMAIL_SUFFIX

# CRM Contact.readiness_level Select stores the full bilingual label.
_READINESS_LABELS = {
	"Level 0": "Level 0 - Chưa xác định",
	"Level 1": "Level 1 - Đang tìm hiểu",
	"Level 2": "Level 2 - Đang so sánh",
	"Level 3": "Level 3 - Có ý định nộp hồ sơ",
	"Level 4": "Level 4 - Sẵn sàng nhập học",
}
SEED = 20260830
SALE_EMAIL = "nguyen-minh-khoi.sale@example.test"
LEAD_SALES_EMAIL = "le-thanh-huong.leadsales@example.test"
MARKETING_EMAIL = "pham-bao-chau.marketing@example.test"
# The school relationship domain (CRM Person / School Activity / key accounts) is
# owned by the Promoter portfolio, not the Sales roles seed_staff creates.
PROMOTER_EMAIL = "vo-thi-lan.promoter@example.test"
PROMOTER_FULL_NAME = "Võ Thị Lan"

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
	}
	try:
		for key, value in LOCAL_FLAGS.items():
			frappe.conf[key] = value
		frappe.flags.crm_governance_additive = True
		frappe.flags.crm_governance_change = True
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
	if getattr(frappe.local, "site", None) != LOCAL_SITE:
		frappe.throw("The curated CRM demo seed only runs on crm.localhost.", frappe.PermissionError)


def _assert_integrity_keys() -> None:
	from crm.fcrm.student_intake import _secret_versions
	from crm.fcrm.student_ownership import _configured_secret

	if not _secret_versions() or not _configured_secret("v1"):
		frappe.throw(
			"Configure the existing Student intake and receipt HMAC keys before running task seed.",
			frappe.ValidationError,
		)


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
	"Transcript Review",
	"National High School Exam",
	"Language Certificate Review",
	"Direct Admission",
	"Combined",
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
		"admission_method": "Combined",
		"email": "nguyen-thao-an.showcase@example.test",
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
		"admission_method": "Language Certificate Review",
		"email": "vo-gia-han.showcase@example.test",
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
		"admission_method": "Transcript Review",
		"email": "bui-minh-khang.showcase@example.test",
		"phone": "0901900103",
		"target_stage": "Applicant",
		"owner": True,
		"summary": "Rà soát hồ sơ xét tuyển còn thiếu bảng điểm có xác nhận",
		"notes": "Hồ sơ đã tiếp nhận, cần gia đình bổ sung bảng điểm học kỳ II có xác nhận.",
		"outcome_spec": ("qualified", "task"),
		"next_action": "Lead Sales rà soát hồ sơ thiếu",
		"sla_target": "escalated",
		"score_series": 2,
		"action_specs": (("DOCUMENT_REQUEST", "in-progress"), ("PARENT_CONTACT", "cancelled")),
		"attribution": ("campaign", None),
	},
	{
		"key": "khanh-linh",
		"student_name": "Trần Khánh Linh",
		"gender": "Nữ",
		"admission_method": "National High School Exam",
		"email": "tran-khanh-linh.showcase@example.test",
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
		"admission_method": "Direct Admission",
		"email": "do-nhat-minh.showcase@example.test",
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
		"admission_method": "Combined",
		"email": "le-hai-dang.showcase@example.test",
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
		"admission_method": "Language Certificate Review",
		"email": "trinh-gia-hung.showcase@example.test",
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
		"admission_method": "Transcript Review",
		"email": "pham-quynh-nhu.showcase@example.test",
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
		"admission_method": "National High School Exam",
		"email": "hoang-duc-thanh.showcase@example.test",
		"phone": "0901900203",
		"target_stage": "Lead",
		"owner": True,
		"summary": "Đã quá hạn phản hồi lần đầu",
		"notes": "Đã quá hạn SLA, chờ Lead Sales xử lý.",
		"sla_target": "breached",
		"score_series": 1,
	},
	{
		"key": "sla-paused",
		"student_name": "Ngô Thanh Mai",
		"gender": "Nữ",
		"admission_method": "Language Certificate Review",
		"email": "ngo-thanh-mai.showcase@example.test",
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
		"admission_method": "Direct Admission",
		"email": "dang-gia-bao.showcase@example.test",
		"phone": "0901900205",
		"target_stage": "Lead",
		"owner": True,
		"summary": "SLA cũ bị thay thế sau khi Lead Sales duyệt reset",
		"notes": "Reset SLA được Lead Sales duyệt, mở lượt mới.",
		"sla_target": "superseded",
		"score_series": 1,
	},
	{
		"key": "no-response",
		"student_name": "Lý Tuấn Kiệt",
		"gender": "Nam",
		"admission_method": "Combined",
		"email": "ly-tuan-kiet.showcase@example.test",
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
		"admission_method": "Transcript Review",
		"email": "duong-khanh-vy.showcase@example.test",
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
		"admission_method": "National High School Exam",
		"email": "phan-nhat-ha.showcase@example.test",
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
		"admission_method": "Direct Admission",
		"email": "ho-minh-quan.showcase@example.test",
		"phone": "0901900209",
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
		"admission_method": "Transcript Review",
		"email": "vu-hong-ngoc.showcase@example.test",
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
		"admission_method": "Combined",
		"email": "huynh-gia-phuc.showcase@example.test",
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
# so the complete showcase namespace lands on exactly 100 students.
TARGET_SHOWCASE_STUDENTS = 100
TARGET_SHOWCASE_CONTACTS = 80
_EDGE_STUDENT_COUNT = 5
_BULK_SCENARIO_COUNT = max(0, TARGET_SHOWCASE_STUDENTS - len(SCENARIOS) - _EDGE_STUDENT_COUNT)
_BULK_ADMISSION_METHODS = (
	"Combined", "Direct Admission", "Language Certificate Review",
	"National High School Exam", "Transcript Review",
)


def _make_bulk_scenario(index: int) -> dict[str, Any]:
	sequence = index + 1
	key = f"bulk-student-{sequence:03d}"
	return {
		"key": key,
		"student_name": f"Học sinh showcase liên kết {sequence:03d}",
		"gender": "Nữ" if sequence % 2 else "Nam",
		"admission_method": _BULK_ADMISSION_METHODS[index % len(_BULK_ADMISSION_METHODS)],
		"email": f"{key}.showcase@example.test",
		"phone": f"090191{sequence:04d}",
		"target_stage": "Lead",
		"owner": sequence % 2 == 0,
		"summary": "Hồ sơ showcase dùng để kiểm tra danh sách và liên kết CRM.",
		"notes": "Dữ liệu tổng hợp deterministic cho local demo; không phải dữ liệu thật.",
		"score_series": 1,
	}


BULK_SCENARIOS: tuple[dict[str, Any], ...] = tuple(
	_make_bulk_scenario(index) for index in range(_BULK_SCENARIO_COUNT)
)
SCENARIOS = SCENARIOS + BULK_SCENARIOS

# CRM Contact rows. New Contacts are inserted under the student_conversion_service
# flag; an idempotent re-run refreshes the frozen case columns with a consolidated
# direct write (see _seed_contacts).
# Contacts stay on their own plane: they link to Students only through the shared
# dimensions (high_school, major, source, admission_year) and, for the converted
# scenario, a CRM Student Contact Conversion row -- never CRM Contact.student,
# which the controller keeps read-only.
CONTACT_ROWS: tuple[dict[str, Any], ...] = (
	{"key": "c-new", "full_name": "Trịnh Bảo Long", "lead_status": "Mới", "enrollment_status": "Mới", "readiness_level": "Level 0", "quality_bucket": "Warm", "decision_maker": "Student", "preferred_contact_channel": "Phone", "is_verified_lead": 0, "consent": "Granted"},
	{"key": "c-unassigned", "full_name": "Cao Thùy Dương", "lead_status": "Unassigned", "enrollment_status": "Mới", "readiness_level": "Level 0", "quality_bucket": "Cool", "decision_maker": "Parent", "preferred_contact_channel": "Zalo", "is_verified_lead": 0, "consent": "Granted"},
	{"key": "c-unclaimed", "full_name": "Đinh Quốc Anh", "lead_status": "Chưa nhận", "enrollment_status": "Mới", "readiness_level": "Level 1", "quality_bucket": "Warm", "decision_maker": "Both", "preferred_contact_channel": "Email", "is_verified_lead": 1, "consent": "Granted"},
	{"key": "c-assigned", "full_name": "Lương Hải Yến", "lead_status": "Assigned", "enrollment_status": "Có triển vọng", "readiness_level": "Level 1", "quality_bucket": "Hot", "decision_maker": "Student", "preferred_contact_channel": "Phone", "is_verified_lead": 1, "owner": True, "consent": "Granted"},
	{"key": "c-just-received", "full_name": "Tạ Minh Trí", "lead_status": "Mới nhận", "enrollment_status": "Có triển vọng", "readiness_level": "Level 2", "quality_bucket": "Hot", "decision_maker": "Student", "preferred_contact_channel": "Zalo", "is_verified_lead": 1, "owner": True, "consent": "Re-subscribed"},
	{"key": "c-counseling-en", "full_name": "Đoàn Thu Trang", "lead_status": "Counseling", "enrollment_status": "Có triển vọng", "readiness_level": "Level 2", "quality_bucket": "Warm", "decision_maker": "Both", "preferred_contact_channel": "Email", "is_verified_lead": 1, "owner": True, "consent": "Granted"},
	{"key": "c-counseling-vi", "full_name": "Bạch Nhật Nam", "lead_status": "Đang tư vấn", "enrollment_status": "Có triển vọng", "readiness_level": "Level 3", "quality_bucket": "Hot", "decision_maker": "Student", "preferred_contact_channel": "Phone", "is_verified_lead": 1, "owner": True, "consent": "Granted"},
	{"key": "c-awaiting-en", "full_name": "Mai Khánh Chi", "lead_status": "Awaiting Documents", "enrollment_status": "Đã xác nhận", "readiness_level": "Level 3", "quality_bucket": "Hot", "decision_maker": "Parent", "preferred_contact_channel": "Zalo", "is_verified_lead": 1, "owner": True, "consent": "Granted"},
	{"key": "c-awaiting-vi", "full_name": "Vương Đức Huy", "lead_status": "Chờ nộp hồ sơ", "enrollment_status": "Đã xác nhận", "readiness_level": "Level 4", "quality_bucket": "Hot", "decision_maker": "Both", "preferred_contact_channel": "Email", "is_verified_lead": 1, "owner": True, "consent": "Granted"},
	{"key": "c-nurture-en", "full_name": "Kiều Thanh Thảo", "lead_status": "Nurture", "enrollment_status": "Có triển vọng", "readiness_level": "Level 1", "quality_bucket": "Cool", "decision_maker": "Student", "preferred_contact_channel": "Zalo", "is_verified_lead": 0, "consent": "Granted"},
	{"key": "c-nurture-vi", "full_name": "Tô Gia Linh", "lead_status": "Nguội", "enrollment_status": "Có triển vọng", "readiness_level": "Level 1", "quality_bucket": "Cool", "decision_maker": "Parent", "preferred_contact_channel": "Phone", "is_verified_lead": 0, "consent": "Suppressed"},
	{"key": "c-won-en", "full_name": "Chu Bảo Ngọc", "lead_status": "Won", "enrollment_status": "Đã nhập học", "readiness_level": "Level 4", "quality_bucket": "Hot", "decision_maker": "Student", "preferred_contact_channel": "Email", "is_verified_lead": 1, "owner": True, "consent": "Granted"},
	{"key": "c-won-vi", "full_name": "Hà Nhật Anh", "lead_status": "Đã chốt", "enrollment_status": "Đã nhập học", "readiness_level": "Level 4", "quality_bucket": "Hot", "decision_maker": "Both", "preferred_contact_channel": "Phone", "is_verified_lead": 1, "owner": True, "consent": "Granted"},
	{"key": "c-lost-en", "full_name": "Lâm Tuệ Nhi", "lead_status": "Lost", "enrollment_status": "Từ chối", "readiness_level": "Level 0", "quality_bucket": "Không quan tâm", "decision_maker": "Student", "preferred_contact_channel": "Zalo", "is_verified_lead": 0, "consent": "Opted Out"},
	{"key": "c-lost-vi", "full_name": "Phùng Quốc Việt", "lead_status": "Từ chối", "enrollment_status": "Từ chối", "readiness_level": "Level 0", "quality_bucket": "Sai số", "decision_maker": "Parent", "preferred_contact_channel": "Phone", "is_verified_lead": 0, "consent": "Marked Test"},
	{"key": "c-unreachable", "full_name": "Trương Mỹ Duyên", "lead_status": "Nguội", "enrollment_status": "Mới", "readiness_level": "Level 0", "quality_bucket": "Không liên lạc được", "decision_maker": "Student", "preferred_contact_channel": "Phone", "is_verified_lead": 0, "consent": "Bounced"},
)


_BULK_CONTACT_COUNT = max(0, TARGET_SHOWCASE_CONTACTS - len(CONTACT_ROWS))
_BULK_CONTACT_LEAD_STATUSES = (
	"Mới", "Unassigned", "Assigned", "Mới nhận", "Counseling", "Đang tư vấn",
	"Awaiting Documents", "Nurture", "Won", "Lost",
)
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
		"full_name": f"Học sinh showcase liên kết {sequence:03d}",
		"lead_status": _BULK_CONTACT_LEAD_STATUSES[index % len(_BULK_CONTACT_LEAD_STATUSES)],
		"enrollment_status": _BULK_CONTACT_ENROLLMENT_STATUSES[index % len(_BULK_CONTACT_ENROLLMENT_STATUSES)],
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
	("FPTU 2025 Early Bird Admission", "Completed", "Off-Campus"),
	("FPTU 2026 Fall Scholarship Drive", "Draft", "On-Campus"),
	("FPTU 2026 Regional Roadshow", "Approved", "Off-Campus"),
	("FPTU 2025 Referral Pilot", "Cancelled", "On-Campus"),
)
_SHOWCASE_CAMPAIGN_TITLES = [title for title, _, _ in _SHOWCASE_CAMPAIGNS]
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
	"CRM Student": {
		"lifecycle_stage": ["Lead", "MQL", "Applicant", "Enrolled", "Lost"],
		"admission_method": list(_ADMISSION_METHODS),
		"gender": ["Nam", "Nữ"],
		"intake_integrity_state": ["resolved", "review_required", "quarantined", "legacy"],
	},
	"CRM Student SLA Attempt": {
		"status": [
			"open", "paused", "warned", "responded", "breached",
			"escalated", "closed", "closed_inactive", "superseded",
		],
	},
	"CRM Student Identity": {"identity_status": ["active", "retracted"]},
	"CRM Student Intake Review": {
		"review_type": [
			"identity_conflict", "duplicate_case", "malformed_identifier",
			"missing_admission_cycle", "ownership_topology", "legacy_contact_origin",
		],
		"review_status": ["open", "attach_identity", "approve_new_identity", "reject", "applied"],
	},
	"CRM Student Outcome": {
		"outcome_code": [
			"connected", "qualified", "follow_up_required", "no_response",
			"not_interested", "invalid", "completed",
		],
		"continuity_kind": ["task", "waiting", "terminal"],
	},
	"CRM Action": {
		"action_type": [
			"CALL", "EMAIL", "MESSAGE", "COUNSELING", "MEETING", "EVENT_INVITE",
			"CAMPUS_VISIT", "DOCUMENT_REQUEST", "APPLICATION_SUPPORT",
			"PARENT_CONTACT", "HANDOFF",
		],
		"state": [
			"pending", "accepted", "in-progress", "requires-review", "completed",
			"cancelled", "superseded", "rejected", "deferred",
		],
		"priority": ["high", "medium", "low"],
		"disposition": ["ACT", "MONITOR", "NURTURE"],
	},
	"CRM Contact": {
		"lead_status": [
			"Mới", "Unassigned", "Chưa nhận", "Assigned", "Mới nhận", "Counseling",
			"Đang tư vấn", "Awaiting Documents", "Chờ nộp hồ sơ", "Nurture", "Nguội",
			"Won", "Đã chốt", "Lost", "Từ chối",
		],
		"readiness_level": list(_READINESS_LABELS.values()),
		"quality_bucket": [
			"Hot", "Warm", "Cool", "Sai số", "Không liên lạc được", "Không quan tâm",
		],
		"decision_maker": ["Student", "Parent", "Both"],
		"preferred_contact_channel": ["Email", "Zalo", "Phone"],
		"is_verified_lead": ["0", "1"],
	},
	"CRM Contact Consent Event": {
		"event_type": [
			"Granted", "Opted Out", "Re-subscribed", "Marked Test", "Bounced", "Suppressed",
		],
	},
	"CRM Interaction": {
		"outcome": [
			"Captured", "Follow Up Needed", "Resolved", "Converted",
			"No Response", "Data Error", "Uncontactable",
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
		"key_account_status": ["Eligible", "Not Eligible", "Review Required"],
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


def _ensure_interaction_type(name: str) -> str:
	if frappe.db.exists("CRM Term", name):
		return name
	return frappe.get_doc(
		{"doctype": "CRM Term", "term_name": name, "category": "interaction_type"}
	).insert(ignore_permissions=True).name


def _ensure_term(term_name: str, category: str) -> str:
	"""Ensure a CRM Term row exists for a non-governed demo category."""
	name = frappe.db.get_value("CRM Term", {"term_name": term_name, "category": category}, "name")
	if name:
		return name
	return frappe.get_doc(
		{"doctype": "CRM Term", "term_name": term_name, "category": category}
	).insert(ignore_permissions=True).name


def _ensure_lead_statuses() -> None:
	rows = [
		("Mới", 10), ("Unassigned", 10), ("Chưa nhận", 10), ("Assigned", 15),
		("Mới nhận", 15), ("Counseling", 20), ("Đang tư vấn", 20),
		("Awaiting Documents", 30), ("Chờ nộp hồ sơ", 30), ("Nurture", 35),
		("Nguội", 35), ("Won", 40), ("Đã chốt", 40), ("Lost", 50), ("Từ chối", 50),
	]
	for name, order in rows:
		if not frappe.db.exists("CRM Term", {"term_name": name, "category": "lead_status"}):
			frappe.get_doc(
				{"doctype": "CRM Term", "term_name": name, "category": "lead_status", "sort_order": order}
			).insert(ignore_permissions=True)


def _ensure_lifecycle_statuses() -> None:
	from crm.demo.seed_student import _ensure_enrollment_status

	for name, order, category, stage in (
		("Mới", 10, "open", "Lead"),
		("Có triển vọng", 20, "open", "MQL"),
		("Đã xác nhận", 30, "open", "Applicant"),
		("Đã nhập học", 40, "enrolled", "Enrolled"),
		("Từ chối", 50, "lost", "Lost"),
	):
		_ensure_enrollment_status(name, order, category, stage)
	_ensure_lead_statuses()


def _enrollment_term(term_name: str) -> str:
	name = frappe.db.get_value(
		"CRM Term", {"term_name": term_name, "category": "enrollment_status"}, "name"
	)
	if not name:
		raise frappe.ValidationError(f"enrollment_status term {term_name!r} missing.")
	return name


# ---------------------------------------------------------------------------
# Org topology + policy history
# ---------------------------------------------------------------------------

def _ensure_policies(campus: str, pool: str) -> None:
	"""Seed one active + one draft + one retired routing and SLA policy each."""
	from crm.api.student_policy import _service_save

	now = now_datetime() - timedelta(minutes=1)
	base = {"campus": campus, "student_pool": pool, "authored_by": "Administrator"}
	specs = (
		{
			"doctype": "CRM Student Routing Policy", "policy_key": f"{NAMESPACE}-routing-v1",
			"policy_version": 1, "strategy": "round_robin", "effective_from": now, "status": "active",
		},
		{
			"doctype": "CRM Student Routing Policy", "policy_key": f"{NAMESPACE}-routing-v2",
			"policy_version": 2, "strategy": "round_robin", "effective_from": now, "status": "draft",
		},
		{
			"doctype": "CRM Student Routing Policy", "policy_key": f"{NAMESPACE}-routing-v0",
			"policy_version": 3, "strategy": "round_robin", "effective_from": now, "status": "retired",
		},
		{
			"doctype": "CRM Student SLA Policy", "policy_key": f"{NAMESPACE}-sla-v1", "policy_version": 1,
			"warning_minutes": 15, "breach_minutes": 30, "escalation_minutes": 45,
			"pause_reasons": json.dumps(["parent_unavailable", "awaiting_documents"]),
			"maximum_pause_minutes": 240,
			"recipient_strategy": "owner_warning_lead_breach_director_escalation",
			"effective_from": now, "status": "active",
		},
		{
			"doctype": "CRM Student SLA Policy", "policy_key": f"{NAMESPACE}-sla-v2", "policy_version": 2,
			"warning_minutes": 10, "breach_minutes": 25, "escalation_minutes": 40,
			"pause_reasons": json.dumps([]), "maximum_pause_minutes": 0,
			"recipient_strategy": "owner_warning_lead_breach_director_escalation",
			"effective_from": now, "status": "draft",
		},
		{
			"doctype": "CRM Student SLA Policy", "policy_key": f"{NAMESPACE}-sla-v0", "policy_version": 3,
			"warning_minutes": 20, "breach_minutes": 40, "escalation_minutes": 60,
			"pause_reasons": json.dumps([]), "maximum_pause_minutes": 0,
			"recipient_strategy": "owner_warning_lead_breach_director_escalation",
			"effective_from": now, "status": "retired",
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
	existing = frappe.db.get_value("CRM Student", {"email": scenario["email"]}, "name")

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
				"enrollment_status": "Mới",
				"high_school": context["high_school"],
				"major": context["major"],
				"source": context["source"],
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
		except Exception as exc:  # noqa: BLE001
			if "replay target is no longer available" in str(exc):
				frappe.db.rollback()
				result = _do_intake(f":r{frappe.generate_hash(length=6)}")
			else:
				raise
		student_name = result.get("student")
		if result.get("outcome") not in {"created", "attached"} or not student_name:
			raise frappe.ValidationError(f"Intake did not create Student {scenario['key']}: {result}")
	doc = frappe.get_doc("CRM Student", student_name)
	if not doc.lifecycle_stage and doc.enrollment_status:
		stage = get_lifecycle_stage(doc.enrollment_status) or "Lead"
		frappe.db.set_value("CRM Student", student_name, "lifecycle_stage", stage, update_modified=False)
		doc.reload()
	# admission_method is a plain Student profile field with no intake-payload
	# path; set it directly so every admission_method value is represented and
	# the academic tab is not blank.
	if doc.admission_method != scenario["admission_method"]:
		frappe.db.set_value(
			"CRM Student", student_name, "admission_method",
			scenario["admission_method"], update_modified=False,
		)
	return doc


def _ensure_assigned(student: str) -> str | None:
	from crm.fcrm.student_routing import (
		enqueue_student_routing,
		process_routing_request,
		retry_student_routing,
	)

	doc = frappe.get_doc("CRM Student", student)
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
	return frappe.get_doc(
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
	).insert(ignore_permissions=True).name


def _ensure_verified_call_interaction(student: str, scenario: dict, *, outcome: str = "Captured") -> str:
	from crm.fcrm.interaction_log import create_interaction

	_ensure_interaction_type("Connected")
	call_id = _idempotency_key(scenario["key"], "sla-response-call")
	call_name = frappe.db.get_value("Call Log", {"id": call_id}, "name")
	if not call_name:
		student_doc = frappe.get_doc("CRM Student", student)
		call_name = frappe.get_doc(
			{
				"doctype": "Call Log", "id": call_id, "from": student_doc.phone, "to": "02873005588",
				"type": "Outgoing", "status": "Completed", "duration": 420, "start_time": now_datetime(),
				"reference_doctype": "CRM Student", "reference_docname": student, "caller": SALE_EMAIL,
			}
		).insert(ignore_permissions=True).name
	interaction = frappe.db.get_value(
		"CRM Interaction", {"reference_doctype": "Call Log", "reference_docname": call_name}, "name"
	)
	if not interaction:
		interaction = create_interaction(
			interaction_type="Connected", student=student, reference_doctype="Call Log",
			reference_docname=call_name, actor=SALE_EMAIL, summary=scenario["summary"],
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
		expected_revision=int(frappe.db.get_value("CRM Student", student, "engagement_revision") or 0),
		idempotency_key=_idempotency_key("outcome", scenario["key"]),
		correlation_id=_idempotency_key(scenario["key"]),
	)
	return result["event"]


def _ensure_document_evidence(student: str, scenario: dict) -> str:
	file_name = f"{scenario['key']}-phieu-tiep-nhan-ho-so.txt"
	existing = frappe.db.get_value(
		"File",
		{"attached_to_doctype": "CRM Student", "attached_to_name": student, "file_name": file_name},
		"name",
	)
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "File", "file_name": file_name, "is_private": 1,
			"content": f"Phiếu tiếp nhận hồ sơ tuyển sinh\nHọc sinh: {scenario['student_name']}\n",
			"attached_to_doctype": "CRM Student", "attached_to_name": student,
		}
	).insert(ignore_permissions=True).name


def _ensure_intent_evidence(student: str, scenario: dict) -> str:
	interaction = _ensure_manual_interaction(student, scenario)
	intent_type = seed_demo._ensure_intent_type("Scholarship", "High", "Quan tâm đến học bổng")
	existing = frappe.db.get_value(
		"CRM Intent", {"interaction": interaction, "intent_type": intent_type}, "name"
	)
	if existing:
		return existing
	return frappe.get_doc(
		{
			"doctype": "CRM Intent", "interaction": interaction, "intent_type": intent_type,
			"confidence": 88, "intent_role": "Dominant", "polarity": "Positive",
			"notes": "Học sinh cần tư vấn điều kiện học bổng.",
		}
	).insert(ignore_permissions=True).name


def _ensure_lifecycle(student: str, scenario: dict, outcome: str | None) -> None:
	from crm.fcrm.student_lifecycle import reopen, request_transition

	target = scenario["target_stage"]
	doc = frappe.get_doc("CRM Student", student)

	if scenario.get("lost_then_reopen") and not frappe.db.exists(
		"CRM Student Lifecycle Event", {"student": student, "transition_kind": "reopen"}
	):
		# Lost -> Reopen -> forward, so the reopen path and prior-active resume
		# are both exercised for one case.
		if doc.lifecycle_stage in {"Lead"}:
			request_transition(
				student, "MQL", reason="Đủ điều kiện chuyển MQL.",
				evidence_refs=[
					{"category": "outcome", "doctype": "CRM Student Outcome", "name": outcome},
					{"category": "intent", "doctype": "CRM Intent", "name": _ensure_intent_evidence(student, scenario)},
				],
				outcome_code="qualified",
				expected_revision=int(doc.lifecycle_revision or 0),
				idempotency_key=_idempotency_key("lifecycle", scenario["key"], "mql"),
				correlation_id=_idempotency_key(scenario["key"]),
			)
			doc.reload()
		request_transition(
			student, "Lost", reason="Tạm dừng theo yêu cầu gia đình.",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_idempotency_key("lifecycle", scenario["key"], "lost"),
			correlation_id=_idempotency_key(scenario["key"]),
		)
		doc.reload()
		reopen(
			student, reason="Gia đình liên hệ lại và tiếp tục quan tâm.",
			expected_revision=int(doc.lifecycle_revision or 0),
			idempotency_key=_idempotency_key("lifecycle", scenario["key"], "reopen"),
			correlation_id=_idempotency_key(scenario["key"]),
		)
		return

	if doc.lifecycle_stage == target or doc.lifecycle_stage != "Lead":
		return
	if target == "Lost":
		request_transition(
			student, "Lost", reason="Gia đình đã chọn chương trình đào tạo khác.",
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
				{"category": "intent", "doctype": "CRM Intent", "name": _ensure_intent_evidence(student, scenario)}
			)
		else:
			evidence.append(
				{"category": "document", "doctype": "File", "name": _ensure_document_evidence(student, scenario)}
			)
		request_transition(
			student, stage, reason=f"Đủ bằng chứng nghiệp vụ để chuyển sang {stage}.",
			evidence_refs=evidence, outcome_code="qualified",
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
		student_doc = frappe.get_doc("CRM Student", student)
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
			fit_score=fit, engagement_score=engagement, intent_score=intent,
			time_decay_score=0, negative_score=negative, final_score=final,
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
		"CRM Student SLA Attempt", filters={"student": student},
		fields=["name"], order_by="creation desc", limit_page_length=1,
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
		return pause_sla(attempt.name, "parent_unavailable", expected_revision=int(attempt.revision or 0))
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
		attempt.name, reason="Reconcile the deterministic demo SLA showcase.",
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
			student, action_type, f"{action_type} — {scenario['summary']}",
			idempotency_key=idem, due_at=now_datetime() + timedelta(hours=4 + index),
			priority=priority, assignee_staff=owner_staff,
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
			("completed", {"outcome_code": "APPLICATION_COMPLETED", "evidence": "Đã hoàn tất theo kế hoạch."}),
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
			action_name, expected_revision=int(action.action_revision or 1), status=status,
			idempotency_key=f"{idem}:{status}:{offset}", _internal_service=True, **extra,
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
				student, context["campaign"], source="Manual",
				notes=f"Open Day — {scenario['student_name']}.",
				idempotency_key=key, correlation_id=_idempotency_key(scenario["key"]),
			)
	if event_kind:
		key = _idempotency_key("event", scenario["key"])
		if not frappe.db.exists(
			"CRM Marketing Engagement", {"engagement_kind": "event_participation", "idempotency_key": key}
		):
			try:
				record_event_participation(
					student, context["event"],
					status="Checked-in" if event_kind == "event_checked_in" else "Registered",
					idempotency_key=key, correlation_id=_idempotency_key(scenario["key"]),
				)
			except Exception as exc:  # noqa: BLE001
				# The doctype also dedups per (student, event); a pre-existing row
				# from another path already gives the coverage we need.
				if "already has a participation record" not in str(exc):
					raise


def _maybe_convert(student: str, scenario: dict) -> None:
	if not scenario.get("convert"):
		return
	from crm.fcrm.student_conversion import convert_student

	doc = frappe.get_doc("CRM Student", student)
	if doc.lifecycle_stage != "Enrolled" or doc.intake_integrity_state != "resolved":
		return
	# convert_student is replay-safe (command receipt + existing-conversion guard).
	convert_student(
		student, expected_lifecycle_revision=int(doc.lifecycle_revision or 0),
		idempotency_key=_idempotency_key("convert", scenario["key"]),
		correlation_id=_idempotency_key(scenario["key"]),
	)


# ---------------------------------------------------------------------------
# Driver loops
# ---------------------------------------------------------------------------

def _seed_students(context: dict, staff_context: dict) -> tuple[list[dict], list[dict]]:
	manifest: list[dict] = []
	errors: list[dict] = []
	pool = staff_context["pool"]
	for scenario in SCENARIOS:
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
				_ensure_actions(student, scenario, owner_staff or frappe.db.get_value("CRM Student", student, "owner_staff"))
			_maybe_convert(student, scenario)
			# Commit the completed scenario so a later failure cannot roll it (or
			# the shared setup) back and leave the manifest claiming success. Some
			# Student service commands commit their own receipts mid-scenario, so a
			# savepoint cannot bound the unit of work -- the scenario is the unit.
			frappe.db.commit()
			manifest.append(
				{
					"key": scenario["key"], "student": student,
					"lifecycle_stage": frappe.db.get_value("CRM Student", student, "lifecycle_stage"),
					"sla": scenario.get("sla_target"),
				}
			)
		except Exception as exc:  # noqa: BLE001 - isolate this scenario, keep going
			# Drop only the failed scenario's uncommitted work; everything through
			# the previous scenario is already committed.
			try:
				frappe.db.rollback()
			except Exception:  # noqa: BLE001
				pass
			errors.append({"key": scenario["key"], "error": str(exc)})
	return manifest, errors


def _seed_contacts(context: dict, staff_context: dict) -> list[dict]:
	if not frappe.db.table_exists("CRM Contact"):
		return []
	sale_staff = staff_context["staff_by_user"].get(SALE_EMAIL)
	team = staff_context["team"]
	campus = staff_context["campus"]
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
				email = f"{row['key']}.{NAMESPACE}@example.test"
				assigned = sale_staff if row.get("owner") else None
				fields = {
					"full_name": row["full_name"],
					"phone": f"09018{_rng('contact', row['key']).randint(10000, 99999)}",
					"enrollment_status": resolved[row["key"]],
					"lead_status": row["lead_status"],
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
				# Contacts intentionally do not write CRM Contact.student: that field
				# is a read-only legacy compatibility link. Bulk rows still carry a
				# stable Student counterpart and inherit its shared CRM dimensions so
				# list/report joins never point at an unrelated case.
				student_key = row.get("student_key")
				if student_key:
					student = frappe.db.get_value(
						"CRM Student", {"email": f"{student_key}.showcase@example.test"},
						["high_school", "major", "source", "admission_year"], as_dict=True,
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
				name = frappe.db.get_value("CRM Contact", {"email": email}, "name")
				if name:
					# Idempotent refresh: many of these columns are PROTECTED_CASE_FIELDS
					# the controller freezes once a Contact exists (post-conversion
					# identity record). A curated demo row is re-applied with a
					# consolidated direct write rather than reopening that guard.
					frappe.db.set_value("CRM Contact", name, fields, update_modified=False)
				else:
					name = frappe.get_doc(
						{"doctype": "CRM Contact", "email": email, **fields}
					).insert(ignore_permissions=True).name
				_ensure_consent_event(name, row["consent"])
				created.append({"key": row["key"], "contact": name})
			except Exception as exc:  # noqa: BLE001
				try:
					frappe.db.rollback(save_point=sp)
				except Exception:  # noqa: BLE001
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
	if not frappe.db.exists(
		"CRM Contact Consent Event", {"contact": contact, "event_type": event_type}
	):
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
		frappe.db.set_value("CRM Contact", contact, column, value, update_modified=False)


# ---------------------------------------------------------------------------
# School domain
# ---------------------------------------------------------------------------

_SCHOOL_AREAS = ("KV1", "KV2", "KV2_NT", "KV3")
_PERSON_REL = ("New", "Active", "Dormant", "Do Not Contact")
_PERSON_INF = ("Low", "Medium", "High", "Decision Maker")
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
				"doctype": "User", "email": PROMOTER_EMAIL, "first_name": first,
				"last_name": last, "user_type": "System User", "enabled": 1,
				"language": "vi", "send_welcome_email": 0,
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
			"CRM Staff", staff_name,
			{"full_name": PROMOTER_FULL_NAME, "campus": campus, "department": department, "is_active": 1},
			update_modified=False,
		)
	else:
		staff_name = frappe.get_doc(
			{
				"doctype": "CRM Staff", "full_name": PROMOTER_FULL_NAME, "user": PROMOTER_EMAIL,
				"department": department, "campus": campus, "is_active": 1,
			}
		).insert(ignore_permissions=True).name
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
	"""Import the real school domain from the workbooks, then curate key accounts.

	The base data (CRM Province / Ward / High School, plus annual snapshots and
	stakeholders for the TS key-account list) comes straight from
	``school_domain_import`` -- no synthetic schools. On top of that this seed
	guarantees COVERAGE_MATRIX state on ``_KEY_ACCOUNT_SLOTS`` real key-account
	schools and gives each three CRM School Activity rows (Planned / Completed /
	Cancelled). Every top-up row is tagged ``source_file = NAMESPACE`` and owned
	by the Promoter staff.

	Curation only runs when the TS workbook was actually imported this run, so a
	machine without it never mutates (let alone deletes) imported real data; the
	school matrix is then reported as an explicit gap instead.
	"""
	from crm.demo import school_domain_import

	counts: dict[str, Any] = {
		"base_import": {}, "ts_import": {},
		"key_account_schools": 0, "activities": 0, "persons": 0, "gaps": [],
	}
	promoter = _ensure_promoter_fixture(staff_context)

	prev_user = frappe.session.user
	prev_ignore = frappe.flags.get("ignore_permissions")
	frappe.set_user("Administrator")
	frappe.flags.ignore_permissions = True
	try:
		if not school_domain_import.DEFAULT_SCHOOL_SEED_PATH.exists():
			counts["gaps"].append(
				{"stage": "workbook", "error": f"missing {school_domain_import.DEFAULT_SCHOOL_SEED_PATH.name}"}
			)
			return counts
		base = school_domain_import.seed_school_seed(dry_run=False)
		counts["base_import"] = base.get("mutations", {})
		if school_domain_import.DEFAULT_TS_PATH.exists():
			ts = school_domain_import.seed_ts_workbook(dry_run=False)
			counts["ts_import"] = ts.get("mutations", {})
		else:
			counts["gaps"].append(
				{"stage": "workbook", "error": f"missing {school_domain_import.DEFAULT_TS_PATH.name}; "
				 "key-account curation skipped, school matrix will report a gap"}
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
			except Exception as exc:  # noqa: BLE001
				try:
					frappe.db.rollback(save_point=sp)
				except Exception:  # noqa: BLE001
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

	Once a school carries a NAMESPACE-tagged activity it stays in the set, so the
	slot -> school mapping never drifts between runs (or between execute() and a
	standalone verify()). New schools are only appended to fill empty slots, taken
	from the TS primary sheet's annual snapshots by name.
	"""
	curated = sorted(set(
		frappe.get_all(
			"CRM School Activity", filters={"source_file": NAMESPACE},
			pluck="high_school", limit_page_length=0,
		)
	))
	out = [s for s in curated if s][:_SHOWCASE_KEY_ACCOUNT_COUNT]
	if len(out) >= _SHOWCASE_KEY_ACCOUNT_COUNT:
		return out
	candidates = sorted(set(
		frappe.get_all(
			"CRM High School Annual Snapshot",
			filters={"source_sheet": school_domain_import.PRIMARY_TS_SHEET},
			pluck="high_school", limit_page_length=0,
		)
	))
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

	# school_area / key_account_tier are plain / permlevel-1 fields the controller
	# does not recompute; pin them so the matrix sees every value. (school_area is
	# deliberately overwritten -- see _KEY_ACCOUNT_SLOTS.)
	frappe.db.set_value("CRM High School", school, "school_area", area, update_modified=False)
	if tier:
		frappe.db.set_value("CRM High School", school, "key_account_tier", tier, update_modified=False)

	# One NAMESPACE-owned stakeholder per curated school covers relationship_status
	# and influence across the first four slots.
	if idx < len(_PERSON_REL):
		person_identity = _idempotency_key("person", school)
		_, state = _upsert(
			"CRM Person",
			{"source_identity": person_identity},
			{
				"full_name": f"Thầy/Cô phụ trách {frappe.db.get_value('CRM High School', school, 'school_name')}",
				"stakeholder_role": role_term,
				"high_school": school,
				"is_active": 1,
				"relationship_status": _PERSON_REL[idx],
				"influence": _PERSON_INF[idx],
				"owner_staff": promoter,
				"phone": f"09019{rng.randint(10000, 99999)}",
				"source_identity": person_identity,
				"source_file": NAMESPACE,
			},
		)
		counts["persons"] += 1 if state in ("created", "updated") else 0

	# Three activities per key-account school: every status, rotating outcomes.
	for slot, status in enumerate(_ACTIVITY_STATUS):
		act_identity = _idempotency_key("activity", school, slot)
		_, state = _upsert(
			"CRM School Activity",
			{"source_identity": act_identity},
			{
				"high_school": school,
				"activity_type": activity_type,
				"activity_date": now_datetime().date() - timedelta(days=30 - slot * 10 + idx),
				"status": status,
				"outcome": _ACTIVITY_OUTCOME[(idx + slot) % len(_ACTIVITY_OUTCOME)],
				"owner_staff": promoter,
				"attendance": 60 - slot * 10 + idx * 5,
				"source_identity": act_identity,
				"source_file": NAMESPACE,
				"source_record_id": act_identity,
			},
		)
		counts["activities"] += 1 if state in ("created", "updated") else 0

	# Snapshot state. The importer writes every snapshot as "Review Required" /
	# "New Enter History" / unlocked with the 2026 row's ne_actual empty; steer the
	# latest row per slot so key_account_status and the snapshot matrix are covered.
	# All writes go through doc.save so validate() recomputes key_account_eligible
	# and fills locked_by / verified_by.
	snaps = frappe.get_all(
		"CRM High School Annual Snapshot",
		filters={"high_school": school},
		fields=["name"],
		order_by="admission_year desc",
		limit_page_length=0,
	)
	if snapshot_mode == "no_snapshot":
		# Controller derives key_account_status "Review Required" with no rows. Only
		# reached right after the importer (re)created these rows this run.
		frappe.db.delete("CRM High School Annual Snapshot", {"high_school": school})
	elif snaps:
		latest = frappe.get_doc("CRM High School Annual Snapshot", snaps[0].name)
		if snapshot_mode == "below_threshold":
			latest.ne_actual = 2
			latest.adjusted_ne_threshold = 50  # -> key_account_status "Not Eligible"
		else:
			latest.ne_actual = 25
			latest.adjusted_ne_threshold = 10  # -> "Eligible" / is_key_account 1
			latest.verification_status = {
				"eligible_verified": "Verified",
				"eligible_rejected": "Rejected",
				"eligible_review": "Review Required",
			}[snapshot_mode]
			latest.ne_actual_semantics = (
				"Official Achieved New Enter" if snapshot_mode == "eligible_verified" else "New Enter History"
			)
			latest.set("is_locked", 1)  # avoid Frappe Document.is_locked property collision
		latest.save(ignore_permissions=True)

	# Re-save so the school's read-only key-account projection matches the snapshot
	# state (this is what lands "Review Required" for the no_snapshot slot).
	frappe.get_doc("CRM High School", school).save(ignore_permissions=True)
	if tier and promoter:
		frappe.db.set_value(
			"CRM High School", school, "key_account_owner", promoter, update_modified=False
		)


# ---------------------------------------------------------------------------
# Marketing
# ---------------------------------------------------------------------------

def _seed_marketing(context: dict, staff_context: dict) -> dict:
	campus = staff_context["campus"]
	mkt_staff = staff_context["staff_by_user"].get(MARKETING_EMAIL)
	campaign_names = []
	for title, status, event_type in _SHOWCASE_CAMPAIGNS:
		name, _ = _upsert(
			"CRM Campaign", {"title": title},
			{
				"title": title, "status": status, "event_type": event_type,
				"campus": campus, "budget": 100_000_000, "owner_staff": mkt_staff,
			},
		)
		campaign_names.append(name)

	if frappe.db.table_exists("CRM Campaign Spend"):
		_upsert(
			"CRM Campaign Spend",
			{"crm_campaign": context["campaign"], "notes": f"{NAMESPACE} recorded spend"},
			{
				"spend_date": now_datetime().date(), "lead_source": context["source"],
				"crm_campaign": context["campaign"], "campus": campus, "amount": 25_000_000,
				"impressions": 50_000, "clicks": 1_250, "notes": f"{NAMESPACE} recorded spend",
			},
		)

	if frappe.db.table_exists("CRM Segment"):
		_upsert(
			"CRM Segment", {"title": f"{NAMESPACE}: học sinh THPT quan tâm CNTT"},
			{
				"title": f"{NAMESPACE}: học sinh THPT quan tâm CNTT", "is_public": 1,
				"filters": json.dumps(
					{"groups": [{"conditions": [{"field": "source", "operator": "=", "value": context["source"]}]}]}
				),
			},
		)

	# Marketing Engagement source=Migrated / Segment and the missing status
	# values are not reachable through the attribution commands (they only emit
	# Manual campaign_touch / event_participation), so cover them directly.
	_seed_marketing_engagement_variants(campaign_names[0], context)
	return {"campaigns": campaign_names}


def _seed_marketing_engagement_variants(campaign: str, context: dict) -> None:
	if not frappe.db.table_exists("CRM Marketing Engagement"):
		return
	variants = [
		("event_participation", "No-show", "Migrated"),
		("event_participation", "Feedback Given", "Segment"),
		("campaign_touch", "Registered", "Migrated"),
	]
	pool_students = frappe.get_all(
		"CRM Student", filters={"email": ["like", _STUDENT_EMAIL_LIKE]},
		pluck="name", order_by="name", limit_page_length=0,
	)
	if not pool_students:
		return
	prev = frappe.flags.get("student_attribution_migration")
	frappe.flags.student_attribution_migration = True
	try:
		for vi, (kind, status, source) in enumerate(variants):
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
			"CRM Lead Source", {"source_name": source_name},
			{"source_name": source_name, "channel_family": channel},
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
				("Create", "Proposed", "Campus Cần Thơ"),
				("Rename", "Applied", "FPTU HCMC Campus"),
				("Retire", "Rejected", "Nguồn cũ 2019"),
				("Reactivate", "Applied", "Nguồn Facebook 2022"),
				("Supersede", "Cancelled", "Nguồn hợp nhất 2026"),
			]
			for action, status, new_value in specs:
				key = _idempotency_key("mdc", action.lower())
				if frappe.db.exists("CRM Master Data Change", {"idempotency_key": key}):
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
						"reason": f"{NAMESPACE}: {action} demo governance record",
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
				"CRM Education Program", {"program_name": name},
				{"program_name": name, "program_type": program_type},
			)[0]
		)

	# Score Template: seed_demo activates one; add one Draft and one Inactive so
	# the template status filter has every value the demo needs.
	for template_name, status in (("Showcase Draft Template", "Draft"), ("Showcase Inactive Template", "Inactive")):
		if not frappe.db.exists("CRM Score Template", {"template_name": template_name}):
			frappe.get_doc(
				{
					"doctype": "CRM Score Template", "template_name": template_name, "status": status,
					"fit_weight": 0.4, "intent_weight": 0.3, "engagement_weight": 0.3,
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
	student = frappe.db.get_value("CRM Student", {"email": ["like", _STUDENT_EMAIL_LIKE]}, "name")
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
			interaction = frappe.get_doc(
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
			).insert(ignore_permissions=True).name
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

		comp_student = frappe.db.get_value(
			"CRM Student", {"email": ["like", _STUDENT_EMAIL_LIKE], "lifecycle_stage": "Lost"}, "name"
		) or student
		comp_interaction = frappe.db.get_value("CRM Interaction", {"external_id": comp_key}, "name")
		if not comp_interaction:
			comp_interaction = frappe.get_doc(
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
			).insert(ignore_permissions=True).name
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
					frappe.db.get_value("CRM Student", comp_student, "engagement_revision") or 0
				),
				idempotency_key=comp_key,
				correlation_id=comp_key,
			)
		except Exception:  # noqa: BLE001 - coverage-only; a failure just leaves the gap
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
				"doctype": "Call Log", "id": call_id, "from": "0901900000", "to": "02873005588",
				"type": call_type, "status": status, "duration": 0 if status != "Completed" else 90,
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

	# --- CRM Student.intake_integrity_state: review_required / quarantined / legacy
	# submit_intake only ever leaves a *created* Student at 'resolved'; the review
	# and quarantine states live on Students created through conflict-resolution
	# paths that need a second conflicting identity we do not model in the curated
	# set. 'legacy' has no service path at all (migration-only provenance marker).
	for variant, state in (("review", "review_required"), ("quarantine", "quarantined"), ("legacy", "legacy")):
		scenario = {
			"key": f"edge-{variant}",
			"student_name": {"review": "Trần Edge Review", "quarantine": "Lê Edge Quarantine", "legacy": "Phạm Edge Legacy"}[variant],
			"gender": "Nam",
			"admission_method": "Combined",
			"email": f"edge-{variant}.{NAMESPACE}@example.test",
			"phone": f"090190030{['review', 'quarantine', 'legacy'].index(variant)}",
			"target_stage": "Lead",
		}
		try:
			doc = _ensure_student(scenario, context, pool)
			frappe.db.set_value(
				"CRM Student", doc.name, "intake_integrity_state", state, update_modified=False
			)
			notes.append(f"CRM Student {doc.name} intake_integrity_state={state} (no service path)")
		except Exception as exc:  # noqa: BLE001
			notes.append(f"edge intake_integrity_state={state} skipped: {exc}")

	# --- CRM Student Identity.identity_status = retracted
	# No whitelisted retraction command exists in crm/fcrm; retraction is an
	# operational data-fix. Retract the identity of the legacy edge Student.
	legacy_student = frappe.db.get_value(
		"CRM Student", {"email": f"edge-legacy.{NAMESPACE}@example.test"}, ["name", "identity"], as_dict=True
	)
	if legacy_student and legacy_student.get("identity"):
		frappe.db.set_value(
			"CRM Student Identity", legacy_student["identity"], "identity_status", "retracted",
			update_modified=False,
		)
		notes.append(f"CRM Student Identity {legacy_student['identity']} identity_status=retracted (no service path)")

	# --- CRM Student SLA Attempt.status = closed / closed_inactive
	# The SLA state machine (crm_student_sla_attempt.py) allows these transitions
	# but no whitelisted command drives them; they are reconciled by an
	# inactivity job that is not part of the demo. Set on dedicated attempts so
	# the closed SLA queue views are populated.
	for variant, target in (("closed", "closed"), ("closed-inactive", "closed_inactive")):
		scenario = {
			"key": f"edge-sla-{variant}",
			"student_name": f"Đỗ Edge SLA {variant}",
			"gender": "Nữ",
			"admission_method": "Transcript Review",
			"email": f"edge-sla-{variant}.{NAMESPACE}@example.test",
			"phone": f"09019004{['closed', 'closed-inactive'].index(variant):02d}",
			"target_stage": "Lead",
			"summary": "Edge SLA closed state",
			"notes": "Edge SLA closed state fixture.",
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
		except Exception as exc:  # noqa: BLE001
			notes.append(f"edge SLA status={target} skipped: {exc}")

	# --- CRM Action states pending / requires-review (AI origin) / rejected / deferred
	# create_manual_action always emits an 'accepted' action; the pending /
	# rejected / deferred states belong to the recommendation-decision pipeline
	# which needs a CRM Recommendation the demo does not generate.
	base_student, base_owner = (frappe.db.get_value(
		"CRM Student",
		{"email": ["like", _STUDENT_EMAIL_LIKE], "owner_staff": ["is", "set"]},
		["name", "owner_staff"],
	) or (None, None))
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
						base_student, action_type, f"{NAMESPACE} edge action {state}",
						idempotency_key=idem, due_at=now_datetime() + timedelta(days=1),
						priority="low", assignee_staff=base_owner,
					)["action"]
				except Exception as exc:  # noqa: BLE001
					notes.append(f"edge action {state} skipped: {exc}")
					continue
			target_state = state if state in {
				"pending", "requires-review", "rejected", "deferred", "superseded",
			} else "accepted"
			updates: dict[str, Any] = {"state": target_state, "disposition": disposition}
			frappe.db.set_value("CRM Action", action_name, updates, update_modified=False)
			notes.append(f"CRM Action {action_name} state={target_state} disposition={disposition} (no service path)")

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
					"CRM Student Intake Review", doc.name, "review_status", review_status,
					update_modified=False,
				)
			notes.append(f"CRM Student Intake Review {doc.name} {review_type}/{review_status} (no service path)")
		except Exception as exc:  # noqa: BLE001
			notes.append(f"intake review {review_type} skipped: {exc}")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _seed_all() -> dict:
	frappe.set_user("Administrator")
	context = seed_demo.execute()
	staff_context = seed_staff.execute()
	_ensure_lifecycle_statuses()
	_ensure_policies(staff_context["campus"], staff_context["pool"])

	reference = _seed_reference_coverage(context)
	students, student_errors = _seed_students(context, staff_context)
	_seed_vocab_coverage(context)
	contacts = _seed_contacts(context, staff_context)
	school = _seed_school_domain(context, staff_context)
	marketing = _seed_marketing(context, staff_context)
	governance = _seed_governance(context)
	edge = _seed_edge_states(context, staff_context)

	frappe.db.commit()
	return {
		"namespace": NAMESPACE,
		"accounts": {
			"password_site_config": seed_staff.FIXTURE_PASSWORD_SITE_CONFIG_KEY,
			"users": {
				**{email: meta["role"] for email, meta in seed_staff.CANONICAL_FIXTURE_USERS.items()},
				PROMOTER_EMAIL: "Promoter",
			},
		},
		"students": students,
		"student_errors": student_errors,
		"contacts": contacts,
		"school_domain": school,
		"marketing": marketing,
		"governance": governance,
		"reference": reference,
		"edge_states": edge,
		"known_gaps": list(KNOWN_GAPS),
	}


def execute(strict: bool = True) -> dict:
	"""Seed the curated CRM demo dataset on ``crm.localhost`` only.

	With ``strict`` (the default) a non-empty ``student_errors`` raises after the
	manifest is printed, so ``task seed`` fails loudly instead of exiting 0 on a
	partial seed. Pass ``strict=False`` to inspect a partial run.
	"""
	_assert_local_site()
	ensure_local_integrity_keys()
	_assert_integrity_keys()
	with _temporary_local_flags():
		result = _seed_all()
	print(frappe.as_json(result))
	if strict and result.get("student_errors"):
		raise frappe.ValidationError(
			f"Seed completed with {len(result['student_errors'])} scenario error(s); "
			"see student_errors in the manifest above."
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
	except Exception:  # noqa: BLE001 - field absent on this install
		return set()
	return {str(row.get(field)) for row in rows if row.get(field) not in (None, "")}


def _coverage_scope() -> dict[str, dict]:
	"""Row filter per COVERAGE_MATRIX doctype so verify() checks only what this
	seed creates -- a blanket table scan would let rows from seed_e2e /
	seed_playwright / manual QA satisfy the matrix.

	execute() runs the seed_demo + seed_staff bootstrap, so the one fixture this
	seed deliberately reuses -- the single Active score template, which the
	doctype only allows one of -- is included by name.
	"""
	ns = f"%{NAMESPACE}%"
	none = ["__seed_showcase_no_match__"]

	def pluck(doctype, filters, field="name"):
		return frappe.get_all(
			doctype, filters=filters, pluck=field, limit_page_length=0
		) or list(none)

	students = pluck("CRM Student", {"email": ["like", _STUDENT_EMAIL_LIKE]})
	contacts = pluck("CRM Contact", {"email": ["like", f"%{NAMESPACE}@example.test"]})
	identities = [
		i for i in frappe.get_all(
			"CRM Student", filters={"name": ["in", students]}, pluck="identity", limit_page_length=0
		) if i
	] or list(none)
	interactions = list(
		set(pluck("CRM Interaction", {"student": ["in", students]}))
		| set(pluck("CRM Interaction", {"external_id": ["like", ns]}))
	)
	# The school domain is real imported data now; the rows this seed *owns* are the
	# curated key-account schools, resolved through their NAMESPACE-tagged children.
	school_children = set(
		pluck("CRM School Activity", {"source_file": NAMESPACE}, "high_school")
	) | set(pluck("CRM Person", {"source_file": NAMESPACE}, "high_school"))
	schools = sorted(s for s in school_children if s and s != none[0]) or list(none)
	by_student = {"student": ["in", students]}
	return {
		"CRM Student": {"name": ["in", students]},
		"CRM Student SLA Attempt": dict(by_student),
		"CRM Student Identity": {"name": ["in", identities]},
		"CRM Student Intake Review": {"review_key": ["like", ns]},
		"CRM Student Outcome": dict(by_student),
		"CRM Action": dict(by_student),
		"CRM Interaction": {"name": ["in", interactions]},
		"CRM Intent": {"interaction": ["in", interactions]},
		"CRM Contact": {"name": ["in", contacts]},
		"CRM Contact Consent Event": {"contact": ["in", contacts]},
		"CRM High School": {"name": ["in", schools]},
		"CRM High School Annual Snapshot": {"high_school": ["in", schools]},
		"CRM School Activity": {"source_file": NAMESPACE},
		"CRM Person": {"source_file": NAMESPACE},
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
			present = _distinct_values(doctype, field, scope.get(doctype))
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
		"ok": not missing,
	}
	print(frappe.as_json(result))
	if strict and missing:
		raise frappe.ValidationError(
			f"Coverage gaps in {len(missing)} field(s): {sorted(missing)}"
		)
	return result


# Business rows this seed owns: (doctype, field, LIKE pattern). Append-only audit
# / receipt / ledger rows are intentionally left in place. CRM Campaign, CRM
# Education Program and the workbook-imported school domain (CRM Province / Ward /
# High School and the TS annual snapshots) are treated as reference data and kept;
# a full re-demo goes through `bench reinstall` (see reset() docstring).
_RESET_DOCTYPES = (
	("CRM Marketing Engagement", "correlation_id", f"%{NAMESPACE}%"),
	("CRM Master Data Change", "correlation_id", f"%{NAMESPACE}%"),
	("CRM Student Intake Review", "review_key", f"%{NAMESPACE}%"),
	# CRM Contact Consent Event is append-only (on_trash blocks deletion); its
	# rows are left behind with their now-deleted Contact link, like the other
	# audit rows noted below.
	("CRM Score Template", "template_name", "Showcase %"),
	("CRM Lead Source", "source_name", "Showcase %"),
	("CRM School Activity", "source_file", f"%{NAMESPACE}%"),
	("CRM High School Annual Snapshot", "source_file", f"%{NAMESPACE}%"),
	("CRM Person", "source_file", f"%{NAMESPACE}%"),
	("CRM Segment", "title", f"%{NAMESPACE}%"),
	("CRM Campaign Spend", "notes", f"%{NAMESPACE}%"),
	("CRM Student Routing Policy", "policy_key", f"%{NAMESPACE}%"),
	("CRM Student SLA Policy", "policy_key", f"%{NAMESPACE}%"),
)

# Append-only audit rows purged with a raw delete during reset() (crm.localhost
# only) because their on_trash guard blocks delete_doc and a surviving row makes
# the next execute() replay a command against a deleted Student.
_RAW_PURGE_DOCTYPES = (
	("CRM Student Outcome", "source_key"),
	("CRM Contact Consent Event", "note"),
)


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
		# CRM Student + everything keyed to it.
		students = frappe.get_all(
			"CRM Student", filters={"email": ["like", _STUDENT_EMAIL_LIKE]}, pluck="name", limit_page_length=0
		)
		for student in students:
			for dt in ("CRM Action", "CRM Interaction", "Task"):
				for name in frappe.get_all(dt, filters={"student": student}, pluck="name", limit_page_length=0):
					frappe.delete_doc(dt, name, force=True, ignore_permissions=True, delete_permanently=True)
			frappe.delete_doc("CRM Student", student, force=True, ignore_permissions=True, delete_permanently=True)
		deleted["CRM Student"] = len(students)

		contacts = frappe.get_all(
			"CRM Contact", filters={"email": ["like", f"%{NAMESPACE}@example.test"]},
			pluck="name", limit_page_length=0,
		)
		for name in contacts:
			frappe.delete_doc("CRM Contact", name, force=True, ignore_permissions=True, delete_permanently=True)
		deleted["CRM Contact"] = len(contacts)

		for doctype, field, pattern in _RESET_DOCTYPES:
			if not frappe.db.table_exists(doctype):
				continue
			names = frappe.get_all(
				doctype, filters={field: ["like", pattern]}, pluck="name", limit_page_length=0
			)
			for name in names:
				try:
					frappe.delete_doc(doctype, name, force=True, ignore_permissions=True, delete_permanently=True)
				except Exception:  # noqa: BLE001 - referenced by a kept audit row
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
		# receipts from seed_e2e / seed_playwright / manual QA are never touched.
		if frappe.db.table_exists("CRM Student Command Receipt"):
			receipt_filter = {"correlation_token": ["like", f"%{NAMESPACE}%"]}
			deleted["CRM Student Command Receipt"] = frappe.db.count(
				"CRM Student Command Receipt", receipt_filter
			)
			frappe.db.delete("CRM Student Command Receipt", receipt_filter)
		frappe.db.commit()

	result = {"namespace": NAMESPACE, "deleted": deleted, "note": kept_note}
	print(frappe.as_json(result))
	return result
